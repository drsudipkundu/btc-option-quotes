#!/usr/bin/env python3
"""ENTRY-TIME SHADOW recorder ("paperboy") - public Delta data only: no API key, never places an order, never touches any bot.
Sudip's morning point 1 (26-Nov-2026), kept running forever.

For the NEXT expiry (12:00 UTC = 17:30 IST) it takes a paper entry every 30 minutes, from 18:00 IST the day before to 11:00 IST:
  at the entry   : spot x, and the real put and call nearest 2.5 % out of the money (strike, best bid, mark) -> entries.csv
  after expiry   : h = highest, l = lowest, c = close from that entry to expiry (Delta 5-minute candles) -> outcomes.csv
                   plus the real paper result of selling that put + call at the best bid (premium collected - payout at c).
  report         : per entry time: avg up / down / close move, bad-end (95th percentile), real premium, payout, net, paid/prem.
Files: ~/deltabot/entry_shadow/entries.csv, outcomes.csv.   Usage: entry_shadow.py run | once | settle | report [days]"""
import csv, datetime as dt, json, os, socket, sys, time, urllib.request, urllib.parse

_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

API = "https://api.india.delta.exchange"
HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
OUT = os.path.join(HOME, "entry_shadow")
ENT, OUTC = os.path.join(OUT, "entries.csv"), os.path.join(OUT, "outcomes.csv")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
DIST = 0.025
H30 = 1800
EF = ["entry_ts", "exp_ts", "m", "x", "p_sym", "p_k", "p_bid", "p_mark", "c_sym", "c_k", "c_bid", "c_mark"]
OF = ["entry_ts", "exp_ts", "m", "x", "h", "l", "c", "p_k", "c_k", "p_bid", "c_bid", "p_mark", "c_mark"]


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "entry-shadow/1"})
    return json.load(urllib.request.urlopen(req, timeout=15))["result"]


def next_expiry(now):
    e = (now // 86400) * 86400 + 12 * 3600
    return e if e > now else e + 86400


def num(v):
    try:
        return float(v)
    except Exception:
        return None


def quotes(exp_ts, spot, G=get):
    """nearest listed put / call to 2.5 % OTM for that expiry -> dict"""
    tick = G("/v2/tickers", {"contract_types": "call_options,put_options", "underlying_asset_symbols": "BTC",
                             "expiry_date": dt.datetime.fromtimestamp(exp_ts, dt.timezone.utc).strftime("%d-%m-%Y")})
    best = {"P": None, "C": None}
    for t in tick:
        p = str(t.get("symbol", "")).split("-")
        if len(p) != 4 or p[0] not in ("C", "P"):
            continue
        k = float(p[2]); tgt = spot * (1 + DIST) if p[0] == "C" else spot * (1 - DIST)
        d = abs(k - tgt)
        if best[p[0]] is None or d < best[p[0]][0]:
            q = t.get("quotes") or {}
            best[p[0]] = (d, t["symbol"], k, num(q.get("best_bid")), num(t.get("mark_price")))
    return best


def read(f):
    return list(csv.DictReader(open(f))) if os.path.exists(f) else []


def append(f, fields, row):
    new = not os.path.exists(f)
    os.makedirs(OUT, exist_ok=True)
    with open(f, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(fields)
        w.writerow([row.get(k, "") for k in fields])


def record_entry(now, G=get):
    """called every minute: records an entry when a half-hour boundary has just passed and is not recorded yet"""
    b = (int(now) // H30) * H30
    if now - b > 600:
        return None
    exp = next_expiry(b)
    m = (exp - b) // H30
    if not 13 <= m <= 47:
        return None
    if any(int(r["entry_ts"]) == b for r in read(ENT)):
        return None
    spot = float(G("/v2/tickers/BTCUSD")["mark_price"])
    q = quotes(exp, spot, G)
    row = {"entry_ts": b, "exp_ts": exp, "m": m, "x": spot}
    for side, pre in (("P", "p"), ("C", "c")):
        if q[side]:
            row.update({pre + "_sym": q[side][1], pre + "_k": q[side][2], pre + "_bid": q[side][3], pre + "_mark": q[side][4]})
    append(ENT, EF, row)
    return row


def settle(now, G=get):
    done = {int(r["entry_ts"]) for r in read(OUTC)}
    todo = [r for r in read(ENT) if int(r["entry_ts"]) not in done and int(r["exp_ts"]) + 300 <= now]
    cache = {}
    n = 0
    for r in todo:
        e0, ex = int(r["entry_ts"]), int(r["exp_ts"])
        if ex not in cache:
            first = min(int(x["entry_ts"]) for x in todo if int(x["exp_ts"]) == ex)
            cache[ex] = G("/v2/history/candles", {"resolution": "5m", "symbol": "BTCUSD", "start": first, "end": ex})
        cs = [x for x in cache[ex] if e0 <= int(x["time"]) < ex]
        if len(cs) < 0.8 * (ex - e0) / 300:            # data hole: do not settle on bad data
            continue
        cs.sort(key=lambda x: int(x["time"]))
        o = {k: r.get(k, "") for k in OF}
        o.update({"h": max(float(x["high"]) for x in cs), "l": min(float(x["low"]) for x in cs), "c": float(cs[-1]["close"])})
        append(OUTC, OF, o); n += 1
    return n


def pct(a, p):
    a = sorted(a)
    return a[min(len(a) - 1, int(p / 100.0 * len(a)))]


def label(ts):
    t = (ts + 19800) // 60 % 1440
    return "%02d:%02d" % (t // 60, t % 60)


def report(days=None):
    rows = read(OUTC)
    if days:
        cut = time.time() - days * 86400
        rows = [r for r in rows if int(r["entry_ts"]) >= cut]
    by = {}
    for r in rows:
        by.setdefault(int(r["m"]), []).append(r)
    print("paper entries settled: %d   nights: %d%s" % (len(rows), len({r["exp_ts"] for r in rows}), "  (last %d days)" % days if days else ""))
    print("ENTRY IST  n  avg up%  avg dn%  avg|c|%  bad95%  worst%  prem%  paid%  net%  paid/prem   (prem = real best bid of put+call 2.5% out)")
    for m in sorted(by, reverse=True):
        r = by[m]; n = len(r)
        up, dn, cl, big, pr, pa = [], [], [], [], [], []
        for x in r:
            X, h, l, c = float(x["x"]), float(x["h"]), float(x["l"]), float(x["c"])
            u, d = (h - X) / X * 100, (X - l) / X * 100
            up.append(u); dn.append(d); cl.append(abs(c - X) / X * 100); big.append(max(u, d))
            pk, ck = num(x["p_k"]), num(x["c_k"])
            pb = num(x["p_bid"]) if num(x["p_bid"]) is not None else (num(x["p_mark"]) or 0) * 0.95
            cb = num(x["c_bid"]) if num(x["c_bid"]) is not None else (num(x["c_mark"]) or 0) * 0.95
            if pk and ck:
                pr.append((pb + cb) / X * 100)
                pa.append((max(pk - c, 0) + max(c - ck, 0)) / X * 100)
        a = lambda v: sum(v) / len(v) if v else 0
        print("%-9s %3d  %6.2f  %7.2f  %7.2f  %6.2f  %6.1f  %5.3f  %5.3f  %5.3f  %8.2f" % (label(int(r[0]["entry_ts"])), n, a(up), a(dn), a(cl), pct(big, 95), max(big), a(pr), a(pa), a(pr) - a(pa), a(pa) / a(pr) if a(pr) else 0))


def run():
    print("entry-shadow running", flush=True)
    while True:
        try:
            now = time.time()
            r = record_entry(now)
            if r:
                print("entry", label(r["entry_ts"]), "x", r["x"], flush=True)
            if int(now) % 600 < 60:
                n = settle(now)
                if n:
                    print("settled", n, flush=True)
        except Exception as e:
            print("error", repr(e), file=sys.stderr, flush=True)
        time.sleep(60)


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "once"
    if c == "run":
        run()
    elif c == "settle":
        print("settled", settle(time.time()))
    elif c == "report":
        report(int(sys.argv[2]) if len(sys.argv) > 2 else None)
    else:
        spot = float(get("/v2/tickers/BTCUSD")["mark_price"]); e = next_expiry(time.time())
        print("spot", spot, "expiry", dt.datetime.fromtimestamp(e, IST), "quotes", quotes(e, spot))
