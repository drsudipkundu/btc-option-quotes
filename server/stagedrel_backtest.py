#!/usr/bin/env python3
"""stagedrel_backtest - COST of the emergency staged margin release (c18), first look (26-Nov-2026). Read-only analysis; touches no bot, no account.

Question: if the emergency bot had cut the sold PUT of the 23:30 night sale whenever BTC fell far enough to threaten the ladder money, what would that have
cost compared with simply holding the put to expiry?

Method (a proxy, hourly BTC only, no real option prices):
 - Night k: entry = open of the 18:00 UTC bar (23:30 IST); expiry = close of the 11:00 UTC bar next day (17:30 IST).
 - Sold put at strike = entry x (1 - 2.5 %) (the normal-night distance), priced with Black-Scholes at the stated volatility. 1 BTC of put.
 - 'Ladder cover D %': the ladder money can carry a fall of D % from the entry price (its critical level). The emergency bot fires when BTC comes within
   5 % of that level, i.e. when BTC is down (D - 5) % from the entry. (D <= 5: it would fire at once - not tested here.)
 - When it fires, it buys back the put at the Black-Scholes price at that moment (spot = the trigger level, time = middle of the bar that touched it)
   plus a slippage of 5 % of the price. Holding instead costs the intrinsic value at expiry.
 - Extra cost of cutting = cut price - hold cost, per 1 BTC of put. Positive = cutting was dearer than holding (BTC rebounded), negative = cutting saved money
   (BTC kept falling).
 - Also shown: the same with only half of the put cut (half the numbers) - simply 0.5 x.
Settings: volatility 50 % and 70 % (the market prices tonight's put with its own IV; 47 % was seen on the call today).
Data: Binance BTCUSDT 1-hour candles (public) from 2020-09 to now. Usage: python3 stagedrel_backtest.py [csv_cache_path]"""
import sys, os, json, math, time, datetime as dt, urllib.request

CACHE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/btc_1h.json"
HOSTS = ["https://api.binance.com", "https://data-api.binance.vision", "https://api1.binance.com"]


def fetch():
    if os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) < 86400:
        return json.load(open(CACHE))
    start = int(dt.datetime(2020, 9, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    out = []
    host = None
    while True:
        got = None
        for h in ([host] if host else HOSTS):
            try:
                u = "%s/api/v3/klines?symbol=BTCUSDT&interval=1h&startTime=%d&limit=1000" % (h, start)
                got = json.load(urllib.request.urlopen(u, timeout=30)); host = h; break
            except Exception as e:
                last = e
        if got is None:
            raise SystemExit("cannot fetch klines: %s" % last)
        if not got:
            break
        out += [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in got]
        start = got[-1][0] + 3600000
        if len(got) < 1000:
            break
        time.sleep(0.15)
    json.dump(out, open(CACHE, "w"))
    return out


def N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def put_bs(S, K, T, v):
    if T <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + 0.5 * v * v * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return K * N(-d2) - S * N(-d1)


def main():
    bars = fetch()
    by = {b[0]: b for b in bars}
    HR = 3600000
    nights = []
    t0 = bars[0][0]
    day = (t0 // (24 * HR)) * 24 * HR
    while day + 18 * HR + 18 * HR <= bars[-1][0] + HR:
        e = day + 18 * HR                                   # 18:00 UTC = 23:30 IST
        seq = [by.get(e + i * HR) for i in range(18)]       # 18:00 .. 11:00 UTC next day
        if all(seq):
            nights.append(seq)
        day += 24 * HR
    print("nights with a full path: %d (%s to %s)" % (len(nights), dt.datetime.utcfromtimestamp(nights[0][0][0] / 1000).date(), dt.datetime.utcfromtimestamp(nights[-1][0][0] / 1000).date()))
    dist = 0.025
    for vol in (0.50, 0.70):
        print("\n=== volatility %.0f %%, put %.1f %% below entry, slippage 5 %%, per 1 BTC of put ===" % (vol * 100, dist * 100))
        print("%-12s %7s %6s %10s %10s %10s %8s %8s" % ("ladder cover", "fired", "% nts", "avg extra", "total", "worst", "saved %", "rebound%"))
        for D in (7, 10, 15, 20, 30):
            thr = (D - 5) / 100.0
            n, tot, worst, saved, reb, fired_by_year = 0, 0.0, -1e18, 0, 0, {}
            for seq in nights:
                S0 = seq[0][1]
                trig = S0 * (1 - thr)
                hit = None
                for i, b in enumerate(seq):
                    if b[3] <= trig:
                        hit = i; break
                if hit is None:
                    continue
                K = S0 * (1 - dist)
                ST = seq[-1][4]
                Tleft = (17.5 - hit - 0.5) / 8760.0 + 0.0     # hours left to expiry, from the middle of the touching bar
                cut = put_bs(trig, K, max(Tleft, 1e-6), vol) * 1.05
                hold = max(K - ST, 0.0)
                extra = cut - hold
                n += 1; tot += extra; worst = max(worst, extra)
                if extra < 0:
                    saved += 1
                if ST > trig * 1.02:
                    reb += 1
                y = dt.datetime.utcfromtimestamp(seq[0][0] / 1000).year
                fired_by_year[y] = fired_by_year.get(y, 0) + 1
            if n:
                print("%-12s %7d %6.1f %10.1f %10.0f %10.1f %8.0f %8.0f   by year %s" % ("D=%d%%" % D, n, 100.0 * n / len(nights), tot / n, tot, worst, 100.0 * saved / n, 100.0 * reb / n,
                      " ".join("%d:%d" % (y, fired_by_year[y]) for y in sorted(fired_by_year))))
            else:
                print("%-12s %7d" % ("D=%d%%" % D, 0))
    print("\nWorst falls: entry to the lowest low of the night (top 8):")
    fall = sorted(((s[0][1] - min(b[3] for b in s)) / s[0][1], s[0][0]) for s in nights)[-8:]
    for f, t in fall:
        print("  %s  %.1f %%" % (dt.datetime.utcfromtimestamp(t / 1000).date(), 100 * f))
    for thr in (2, 5, 10):
        print("nights with a fall of at least %d %% from the entry: %d" % (thr, sum(1 for s in nights if (s[0][1] - min(b[3] for b in s)) / s[0][1] >= thr / 100.0)))


if __name__ == "__main__":
    main()
