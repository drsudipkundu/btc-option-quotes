#!/usr/bin/env python3
"""entry_time_scan - which ENTRY TIME for the daily option sell is better? (26-Nov-2026, Sudip's morning point 1). Analysis only; touches no bot, no account.

For every day and every entry time (every 30 minutes from 18:00 IST to 11:00 IST), measured from that entry's OWN spot x:
  c = close at the next expiry (17:30 IST = 12:00 UTC), h = highest price after the entry until expiry, l = lowest price after the entry until expiry.
Reported as % of x: up move (h - x), down move (x - l), close move |c - x|, the bad end (95th percentile of the larger of up and down), the worst night,
how often a strike 2.5 % away on either side was touched, and an edge proxy: Black-Scholes premium of a 2.5 % OTM put + call (volatility 50 %, fewer hours left
= smaller premium) minus what they actually paid out at expiry. Also the average hourly range by IST hour, by year (the 'hourly volatility' rebuilt).
Data: Binance BTCUSDT 30-minute candles (public), Sep 2020 to now. Usage: python3 entry_time_scan.py [cache.json]"""
import sys, os, json, math, time, datetime as dt, urllib.request

CACHE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/btc_30m.json"
HOSTS = ["https://api.binance.com", "https://data-api.binance.vision", "https://api1.binance.com"]
H30 = 1800000
IST = 19800000


def fetch():
    if os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) < 86400:
        return json.load(open(CACHE))
    start = int(dt.datetime(2020, 9, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    out, host, last = [], None, None
    while True:
        got = None
        for h in ([host] if host else HOSTS):
            try:
                got = json.load(urllib.request.urlopen("%s/api/v3/klines?symbol=BTCUSDT&interval=30m&startTime=%d&limit=1000" % (h, start), timeout=30)); host = h; break
            except Exception as e:
                last = e
        if got is None:
            raise SystemExit("cannot fetch: %s" % last)
        if not got:
            break
        out += [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in got]
        start = got[-1][0] + H30
        if len(got) < 1000:
            break
        time.sleep(0.15)
    json.dump(out, open(CACHE, "w"))
    return out


def N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v, call):
    if T <= 0:
        return max(S - K, 0) if call else max(K - S, 0)
    d1 = (math.log(S / K) + 0.5 * v * v * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if call else K * N(-d2) - S * N(-d1)


def pct(a, p):
    a = sorted(a)
    return a[min(len(a) - 1, int(p / 100.0 * len(a)))]


def ist_label(ts_utc_ms):
    t = (ts_utc_ms + IST) // 60000 % 1440
    return "%02d:%02d" % (t // 60, t % 60)


def main():
    bars = fetch()
    by = {b[0]: b for b in bars}
    first_exp = ((bars[0][0] + 24 * 3600000) // (24 * 3600000)) * 24 * 3600000 + 12 * 3600000
    exps, e = [], first_exp
    while e < bars[-1][0]:
        exps.append(e); e += 24 * 3600000
    res = {}                                            # m -> list of (year, up, down, closemove, touch, prem, payout)
    VOL, DIST = 0.50, 0.025
    for ex in exps:
        year = dt.datetime.utcfromtimestamp(ex / 1000).year
        for m in range(13, 48):                          # entry = expiry - m x 30 min: 11:00 IST ... 18:00 IST the day before
            e0 = ex - m * H30
            seq = [by.get(e0 + i * H30) for i in range(m)]
            if not all(seq):
                continue
            x = seq[0][1]; h = max(b[2] for b in seq); l = min(b[3] for b in seq); c = seq[-1][4]
            Kp, Kc = x * (1 - DIST), x * (1 + DIST)
            T = m * 0.5 / 8760.0
            prem = (bs(x, Kp, T, VOL, False) + bs(x, Kc, T, VOL, True)) / x
            pay = (max(Kp - c, 0) + max(c - Kc, 0)) / x
            res.setdefault(m, []).append((year, (h - x) / x, (x - l) / x, abs(c - x) / x, (l <= Kp or h >= Kc), prem, pay))
    print("days: %d (%s to %s)  vol assumed %.0f %%, strikes +-%.1f %%" % (len(exps), dt.datetime.utcfromtimestamp(exps[0] / 1000).date(), dt.datetime.utcfromtimestamp(exps[-1] / 1000).date(), VOL * 100, DIST * 100))
    print("\nENTRY IST  hrs   n   avg up%  avg dn%  avg |c|%  bad-end95%  worst%  touch2.5%  prem%   paid%   edge%  paid/prem")
    for m in sorted(res, reverse=True):
        r = res[m]; n = len(r)
        lab = ist_label(first_exp - m * H30)
        up = sum(a[1] for a in r) / n * 100; dn = sum(a[2] for a in r) / n * 100; cl = sum(a[3] for a in r) / n * 100
        big = [max(a[1], a[2]) * 100 for a in r]
        tch = sum(1 for a in r if a[4]) / n * 100
        pr = sum(a[5] for a in r) / n * 100; pa = sum(a[6] for a in r) / n * 100
        print("%-9s %5.1f %5d  %7.2f  %7.2f  %8.2f  %10.2f  %6.1f  %9.1f  %6.3f  %6.3f  %6.3f  %8.2f" % (lab, m * 0.5, n, up, dn, cl, pct(big, 95), max(big), tch, pr, pa, pr - pa, pa / pr if pr else 0))
    print("\nEDGE%% (premium - paid) by year for chosen entries")
    picks = [47, 43, 39, 36, 30, 23, 17, 13]            # 18:00 20:00 22:00 23:30 02:30 06:00 09:00 11:00 IST
    print("entry IST:", "  ".join(ist_label(first_exp - m * H30) for m in picks))
    years = sorted(set(a[0] for r in res.values() for a in r))
    for y in years:
        row = []
        for m in picks:
            r = [a for a in res.get(m, []) if a[0] == y]
            row.append("%7.3f" % (sum(a[5] - a[6] for a in r) / len(r) * 100) if r else "    n/a")
        print(y, " ".join(row))
    print("\nAVERAGE RANGE of each IST half-hour bar (high-low as %% of open), by year: hourly volatility rebuilt")
    rng = {}
    for b in bars:
        y = dt.datetime.utcfromtimestamp(b[0] / 1000).year
        rng.setdefault((ist_label(b[0]), y), []).append((b[2] - b[3]) / b[1] * 100)
    labs = sorted(set(k[0] for k in rng))
    print("bar IST  " + " ".join("%6d" % y for y in years) + "   all")
    for lb in labs:
        if lb[:2] in ("18", "19", "20", "21", "22", "23", "00", "01", "02", "03", "05", "09", "12", "15", "17") and lb[3:] == "00":
            allv = [v for y in years for v in rng.get((lb, y), [])]
            print("%-8s " % lb + " ".join("%6.2f" % (sum(rng[(lb, y)]) / len(rng[(lb, y)])) if (lb, y) in rng else "   n/a" for y in years) + "  %5.2f" % (sum(allv) / len(allv)))


if __name__ == "__main__":
    main()
