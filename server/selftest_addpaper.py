#!/usr/bin/env python3
"""selftest_addpaper - fake-exchange test of addpaper.py (paper logger). No network, no order."""
import os, sys, tempfile, json
HERE = os.path.dirname(os.path.abspath(__file__)); TMP = tempfile.mkdtemp(); os.environ["BOT_HOME"] = TMP; sys.path.insert(0, HERE)
import addpaper as A
n = [0]
def ok(c, m):
    if not c: print("FAIL:", m); sys.exit(1)
    n[0] += 1
src = open(os.path.join(HERE, "addpaper.py")).read()
ok("POST" not in src and "api-key" not in src.lower() and "place_order" not in src, "public GET only, no order code")
EXP = 1795867200                       # 28-Nov-2026 12:00 UTC
T0 = EXP - 18 * 3600                   # 23:30 IST
SPOT = [60000.0]
def G(path, params=None):
    if path == "/v2/tickers/BTCUSD":
        return dict(mark_price=SPOT[0])
    if path == "/v2/tickers":
        out = []
        for k in range(50000, 70001, 200):
            for s in ("C", "P"):
                m = max(5.0, 300 - abs(k - SPOT[0]) * 0.1)
                out.append(dict(symbol="%s-BTC-%d-281126" % (s, k), mark_price=m, quotes=dict(best_bid=m * 0.95, best_ask=m * 1.05)))
        return out
    if path == "/v2/history/candles":
        return [dict(time=EXP - 60 * i, close=61000.0) for i in range(1, 31)]
    raise RuntimeError(path)
nolive = lambda exp: {}
ok(A.next_expiry(T0) == EXP, "next expiry")
ok(A.anchor(T0 + 60, G, nolive) is None and A.anchor(T0 + 1500, G, nolive) is None, "anchor only at 23:34-23:50 IST")
A.run(T0 + 300, G, nolive)
st = json.load(open(A.STF))
ok(st["sides"]["C"]["K"] == 61400 and st["sides"]["P"]["K"] == 58400 and st["sides"]["C"]["src"] == "model", "model strikes: %s" % st["sides"])
ok(st["sides"]["C"]["Kh"] == 63800 and st["sides"]["P"]["Kh"] == 56000, "hedge 4% beyond")
A.run(T0 + 600, G, nolive); ok(A.read(A.TRG) == [], "no move -> no trigger")
SPOT[0] = 60650.0; A.run(T0 + 1200, G, nolive)
r = A.read(A.TRG); ok(len(r) == 1 and r[0]["side"] == "C" and float(r[0]["thr"]) == 1.0 and float(r[0]["Kn"]) == 62200 and float(r[0]["Khn"]) == 64600, "1%% up -> call trigger with new strikes: %s" % r)
A.run(T0 + 1320, G, nolive); ok(len(A.read(A.TRG)) == 1, "same trigger is recorded once")
SPOT[0] = 60950.0; A.run(T0 + 3000, G, nolive); ok(len(A.read(A.TRG)) == 2 and float(A.read(A.TRG)[1]["thr"]) == 1.5, "1.5% trigger")
SPOT[0] = 59000.0; A.run(T0 + 7 * 3600, G, nolive); ok(len(A.read(A.TRG)) == 2, "after the 6-hour window nothing is recorded")
ok(A.run(EXP - 100, G, nolive) == 0, "not settled before expiry")
k = A.run(EXP + 400, G, nolive); o = A.read(A.OUTC)
ok(k == 2 and len(o) == 2 and float(o[0]["S"]) == 61000.0, "settled after expiry")
r0 = o[0]; exp_a1 = round(float(r0["bid_same"]) - float(r0["ask_old"]) - 0 + 0, 2)
ok(abs(float(r0["A1"]) - exp_a1) < 0.011, "A1 arithmetic (strike 61400 not reached at 61000)")
ok(A.run(EXP + 800, G, nolive) == 0 and len(A.read(A.OUTC)) == 2, "settled once only")
ok(A.variant("C", 100, 61600, 20, 64000, 65000) == round(100 - 20 - 3400 + 1000, 2), "loss capped by the hedge")
ok(A.variant("C", 100, 62200, 20, 62000, 65000) == "" and A.variant("P", None, 58000, 5, 56000, 60000) == "", "bad hedge order or missing quote -> blank")
ok(A.variant("P", 80, 58400, 10, 56000, 57000) == round(80 - 10 - 1400 + 0, 2), "put payout")
# live strikes are used when the live seller has a position
os.makedirs(os.path.join(TMP, "state"), exist_ok=True)
json.dump(dict(legs=[dict(sym="C-BTC-63000-291126", side="CE", dir="S", strike=63000, closed=False, kind="trend"),
                     dict(sym="C-BTC-65600-291126", side="CE", dir="B", strike=65600, closed=False, kind="wing"),
                     dict(sym="P-BTC-50000-281126", side="PE", dir="S", strike=50000, closed=False, kind="trend")]), open(os.path.join(TMP, "state", "night_nlive.json"), "w"))
lv = A.live_strikes(EXP + 86400); ok(lv == {"C": {"K": 63000.0, "Kh": 65600.0}}, "live strikes for the right expiry only: %s" % lv)
SPOT[0] = 61000.0
a = A.anchor(T0 + 86400 + 300, lambda p, q=None: G(p, q) if p != "/v2/tickers" else [dict(t, symbol=t["symbol"].replace("281126", "291126")) for t in G(p, q)], A.live_strikes)
ok(a["sides"]["C"]["src"] == "live" and a["sides"]["C"]["K"] == 63000 and a["sides"]["P"]["src"] == "model", "live call strike + model put strike")
A.report()
print("SELFTEST ADDPAPER PASSED (%d checks)" % n[0])
