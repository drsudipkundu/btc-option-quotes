#!/usr/bin/env python3
"""Delta India BTCUSD order-book recorder (public data only, no API key, never places orders).
Every INTERVAL seconds: fetch L2 book (depth 1000/side), aggregate into BIN-dollar rows within +-RANGE_PCT of mid,
append one JSON line to ~/deltabot/obook/YYYYMMDD_HH.jsonl.  Finished hours are gzipped.
Line: {"t": unix, "bb": best bid, "ba": best ask, "bin": 25, "b0": first bid row index, "bids": [contracts...], "a0": first ask row index, "asks": [contracts...]}
Row index r means price range [r*bin, (r+1)*bin).  Contracts: 1 contract = 0.001 BTC."""
import gzip, json, os, socket, sys, time, glob
import urllib.request
# force IPv4 (the same dual-stack lesson as the trading bot)
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

URL = "https://api.india.delta.exchange/v2/l2orderbook/BTCUSD?depth=1000"
INTERVAL = int(os.environ.get("OB_INTERVAL", "10"))
BIN = 25
RANGE_PCT = 2.0
OUT = os.path.expanduser(os.environ.get("OB_DIR", "~/deltabot/obook"))
os.makedirs(OUT, exist_ok=True)

def rows(levels, lo, hi):
    m = {}
    for x in levels:
        p = float(x["price"])
        if lo <= p <= hi:
            r = int(p // BIN)
            m[r] = m.get(r, 0) + int(x["size"])
    if not m:
        return None, []
    r0, r1 = min(m), max(m)
    return r0, [m.get(r, 0) for r in range(r0, r1 + 1)]

def snapshot():
    req = urllib.request.Request(URL, headers={"User-Agent": "obook-recorder/1"})
    res = json.load(urllib.request.urlopen(req, timeout=10))["result"]
    buy, sell = res["buy"], res["sell"]
    bb, ba = float(buy[0]["price"]), float(sell[0]["price"])
    mid = (bb + ba) / 2
    lo, hi = mid * (1 - RANGE_PCT / 100), mid * (1 + RANGE_PCT / 100)
    b0, bids = rows(buy, lo, hi)
    a0, asks = rows(sell, lo, hi)
    return {"t": int(time.time()), "bb": bb, "ba": ba, "bin": BIN, "b0": b0, "bids": bids, "a0": a0, "asks": asks}

def gzip_old(current):
    for f in glob.glob(os.path.join(OUT, "*.jsonl")):
        if f != current:
            with open(f, "rb") as s, gzip.open(f + ".gz", "wb", 6) as d:
                d.write(s.read())
            os.remove(f)

def main():
    fails = 0
    while True:
        t0 = time.time()
        try:
            snap = snapshot()
            name = os.path.join(OUT, time.strftime("%Y%m%d_%H", time.localtime()) + ".jsonl")
            with open(name, "a") as f:
                f.write(json.dumps(snap, separators=(",", ":")) + "\n")
            gzip_old(name)
            fails = 0
        except Exception as e:
            fails += 1
            print("snapshot failed:", repr(e), file=sys.stderr, flush=True)
            time.sleep(min(60, 5 * fails))
        time.sleep(max(0, INTERVAL - (time.time() - t0)))

if __name__ == "__main__":
    main()
