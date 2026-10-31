#!/usr/bin/env python3
"""Delta India BTC OPTION order-book recorder (public data only, no API key, never places orders).
Purpose (31-Oct-2026): real option depth for testing the night-sell "smart seller" rules (walk-away price,
retries, further strikes) before live money.

Which options: the next daily expiry, calls and puts 1%..7% out of the money (all listed strikes in that band).
How often: every 30 s in the busy windows (23:10-01:00 IST entry, 16:55-17:35 IST exit),
every 5 minutes the rest of the time (buy-back / crash-guard hours).
One JSON line per option per snapshot -> ~/deltabot/optbook/YYYYMMDD_HH.jsonl (finished hours gzipped):
{"t": unix, "s": symbol, "k": strike, "ty": "C"/"P", "sp": spot, "bids": [[price, contracts], ...20], "asks": [[price, contracts], ...20]}
1 contract = 0.001 BTC."""
import gzip, json, os, socket, sys, time, glob, datetime as dt
import urllib.request, urllib.parse
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

API = "https://api.india.delta.exchange"
OUT = os.path.expanduser(os.environ.get("OPTBOOK_DIR", "~/deltabot/optbook"))
LEVELS = 20
BAND = (0.01, 0.07)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UTC = dt.timezone.utc
os.makedirs(OUT, exist_ok=True)

def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "optbook-recorder/1"})
    return json.load(urllib.request.urlopen(req, timeout=10))["result"]

def next_expiry(now_utc):
    e = now_utc.replace(hour=12, minute=0, second=0, microsecond=0)
    return e if e > now_utc else e + dt.timedelta(days=1)

def pick(now_utc):
    exp = next_expiry(now_utc)
    tick = get("/v2/tickers", {"contract_types": "call_options,put_options", "underlying_asset_symbols": "BTC",
                               "expiry_date": exp.strftime("%d-%m-%Y")})
    spot = float(get("/v2/tickers/BTCUSD")["mark_price"])
    out = []
    for t in tick:
        p = str(t.get("symbol", "")).split("-")
        if len(p) != 4 or p[0] not in ("C", "P"):
            continue
        k = float(p[2])
        d = (k / spot - 1) if p[0] == "C" else (1 - k / spot)
        if BAND[0] <= d <= BAND[1]:
            out.append((t["symbol"], k, p[0]))
    return spot, out

def busy(now_ist):
    m = now_ist.hour * 60 + now_ist.minute
    return m >= 23 * 60 + 10 or m <= 60 or (16 * 60 + 55 <= m <= 17 * 60 + 35)

def gzip_old(current):
    for f in glob.glob(os.path.join(OUT, "*.jsonl")):
        if f != current:
            with open(f, "rb") as s, gzip.open(f + ".gz", "wb", 6) as d:
                d.write(s.read())
            os.remove(f)

def snap():
    now = dt.datetime.now(UTC)
    spot, syms = pick(now)
    name = os.path.join(OUT, now.astimezone(IST).strftime("%Y%m%d_%H") + ".jsonl")
    t = int(time.time())
    with open(name, "a") as f:
        for s, k, ty in syms:
            try:
                b = get("/v2/l2orderbook/" + s, {"depth": LEVELS})
            except Exception as e:
                print("book failed", s, repr(e), file=sys.stderr, flush=True)
                continue
            f.write(json.dumps({"t": t, "s": s, "k": k, "ty": ty, "sp": spot,
                                "bids": [[float(x["price"]), int(x["size"])] for x in (b.get("buy") or [])[:LEVELS]],
                                "asks": [[float(x["price"]), int(x["size"])] for x in (b.get("sell") or [])[:LEVELS]]},
                               separators=(",", ":")) + "\n")
            time.sleep(0.15)
    gzip_old(name)

def main():
    fails = 0
    while True:
        t0 = time.time()
        try:
            snap()
            fails = 0
        except Exception as e:
            fails += 1
            print("snapshot failed:", repr(e), file=sys.stderr, flush=True)
            time.sleep(min(120, 10 * fails))
        every = 30 if busy(dt.datetime.now(IST)) else 300
        time.sleep(max(1, every - (time.time() - t0)))

if __name__ == "__main__":
    main()
