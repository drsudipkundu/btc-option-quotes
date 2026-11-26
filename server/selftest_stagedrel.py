#!/usr/bin/env python3
"""selftest_stagedrel - fake exchange test of stagedrel.py (c18, report only). Needs no network and places no order."""
import os, sys, json, tempfile, datetime as dt, types, importlib

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.makedirs(os.path.join(TMP, "state")); os.makedirs(os.path.join(TMP, "logs"))
os.environ["BOT_HOME"] = TMP
sys.path.insert(0, HERE)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
ok_n = [0]


def ok(c, msg):
    if not c:
        print("FAIL:", msg); sys.exit(1)
    ok_n[0] += 1


SPOT = 60000.0
EQ = [10000.0]
ORDERS = []


class FakeLive:
    def __init__(self, name):
        self.name = name

    def _p(self, method, path, params=None):
        if method != "GET":
            ORDERS.append((method, path)); raise AssertionError("report-only code made a non-GET call")
        if path == "/v2/wallet/balances":
            return dict(result=[dict(balance=EQ[0], available_balance=EQ[0] * 0.8 if self.name == "ladder9" else 500.0, blocked_margin=EQ[0] * 0.2 if self.name == "ladder9" else 0.0)])
        if path == "/v2/positions/margined":
            if self.name == "ladder9":
                return dict(result=[dict(product_symbol="BTCUSD", size=110, margin=0.36 * 0.11 * SPOT)])
            return dict(result=[])
        if path == "/v2/orders":
            return dict(result=[])
        raise RuntimeError("not available in the fake: " + path)


class FakePub:
    def _http(self, method, path, *a, **k):
        assert method == "GET"
        if path.endswith("BTCUSD"):
            return dict(result=dict(spot_price=SPOT, mark_price=SPOT, product_id=27))
        sym = path.rsplit("/", 1)[1]
        return dict(result=dict(mark_price={"P-BTC-57400-261127": 40.0, "C-BTC-61800-261127": 7.9, "P-BTC-57400-261127b": 40.0}.get(sym, 5.0)))


lo = types.ModuleType("liveorders"); lo.Live = FakeLive; lo.Pub = FakePub
sys.modules["liveorders"] = lo
import sweep_report as SR
import stagedrel as SD

c = SD.load_cfg()
sc = SR.load_cfg()

# 1. need_window: a window with no grid level inside only needs what is held; deeper window needs more
last_far = SPOT * 0.5
w0 = SD.need_window(SR, sc, SPOT, 0.11, last_far, 0.36, 0.11, 5.0)
ok(w0["nlots"] == 0, "no buy level inside the window when the last buy is far below: nlots %s" % w0["nlots"])
ok(abs(w0["need"] - (0.36 * 0.11 * w0["Pst"] + sc["call_ratio"] * 0.11 * w0["Pst"] + 0.11 * (SPOT - w0["Pst"]))) < 1e-6, "need = margin + loss with no buys")
w1 = SD.need_window(SR, sc, SPOT, 0.11, SPOT * 1.0001, 0.36, 0.11, 5.0)
ok(w1["nlots"] >= 1 and w1["need"] > w0["need"], "buys inside the window raise the need (lots %d)" % w1["nlots"])
w2 = SD.need_window(SR, sc, SPOT, 0.11, SPOT * 1.0001, 0.36, 0.11, 10.0)
ok(w2["need"] > w1["need"], "a 10% window needs more than a 5% window")

# 2. plan_cuts order and limits
now = dt.datetime(2026, 11, 26, 23, 31, tzinfo=IST)
legs = [
    dict(id=1, side="PE", sym="P-BTC-57400-261127", qty=0.180, entry=60.0, t=now.isoformat(), kind="main"),
    dict(id=2, side="CE", sym="C-BTC-61800-261127", qty=1.215, entry=34.5, t=now.isoformat(), kind="main"),
    dict(id=3, side="PE", sym="P-BTC-57400-261127b", qty=0.110, entry=55.0, t=(now + dt.timedelta(minutes=70)).isoformat(), kind="main"),
]
marks = {"P-BTC-57400-261127": 40.0, "C-BTC-61800-261127": 7.9, "P-BTC-57400-261127b": 40.0}
fb_put = SD.freed_per_btc(c, "PE", SPOT, 40.0)
small = fb_put * 0.110 * 0.5
p = SD.plan_cuts(c, SPOT, legs, marks, small)
ok(len(p["steps"]) == 1 and p["steps"][0][0] == "put top-up" and p["steps"][0][1] == 3, "a small need is met by part of the top-up put only: %s" % p["steps"])
ok(p["short"] == 0 and p["freed"] >= small - 1e-6, "need met")
big = fb_put * 0.110 + 3000.0
p = SD.plan_cuts(c, SPOT, legs, marks, big)
labs = [s[0] for s in p["steps"]]
ok(labs[0] == "put top-up" and labs[1] == "call by decay", "order: put top-up, then call by decay: %s" % labs)
call_step = [s for s in p["steps"] if s[0] == "call by decay"][0]
ok(abs(call_step[4] - round(1.215 * (1 - 7.9 / 34.5), 3)) <= 0.002, "call cut = decay share of the call quantity: %s" % call_step[4])
huge = 1e9
p = SD.plan_cuts(c, SPOT, legs, marks, huge)
labs = [s[0] for s in p["steps"]]
ok("put 50% of base" in labs and "put 30% of base" in labs and "put 20% of base" in labs, "all put tiers used when the need is huge: %s" % labs)
ok(p["short"] > 0, "ALERT when everything is not enough")
tot_p = sum(s[4] for s in p["steps"] if s[3] == "PE")
ok(tot_p <= 0.290 + 1e-9, "never more put than is open: %s" % tot_p)
for s in p["steps"]:
    ok(abs(s[4] / 0.001 - round(s[4] / 0.001)) < 1e-6, "whole contracts: %s" % s[4])
ok(all(s[1] in (1, 2, 3) for s in p["steps"]), "only sold legs are touched (hedge legs are never in the plan)")

# 3. end to end with the fake exchange: plenty of money -> sleeps; little money -> plan; nothing but GET calls
st = dict(night="2026-11-26", legs=[dict(l, dir="S", closed=False) for l in legs])
json.dump(st, open(os.path.join(TMP, "state", "night_nlive.json"), "w"))
EQ[0] = 100000.0
d = SD.compute(c, FakeLive, FakePub)
ok(d["gap"] < 0 and d["plan"] is None, "plenty of money: only watching")
ok("only watching" in SD.message(d), "message says only watching")
EQ[0] = 100000.0
d = SD.compute(c, FakeLive, FakePub, fake_eq=d["need_usd"] - 400.0)
ok(d["gap"] > 399 and d["plan"] and d["plan"]["steps"], "dry run with a pretend balance gives a plan")
m = SD.message(d)
for key in ("WOULD CUT", "WOULD MOVE", "Zone values used", "REPORT ONLY", "DRY RUN", "hedge stays"):
    ok(key in m, "message has: " + key)
ok(d["move_usd"] > 0, "would move some money")
ok(not ORDERS, "no order and no non-GET call was made")

print("SELFTEST STAGEDREL PASSED (%d checks)" % ok_n[0])
