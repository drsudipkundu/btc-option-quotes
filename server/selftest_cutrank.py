#!/usr/bin/env python3
"""selftest_cutrank - pure-function test of cutrank.py (paper only). Needs no network and places no order."""
import os, sys, tempfile, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(); os.makedirs(os.path.join(TMP, "state")); os.makedirs(os.path.join(TMP, "logs"))
os.environ["BOT_HOME"] = TMP; sys.path.insert(0, HERE)
n = [0]
def ok(c, m):
    if not c:
        print("FAIL:", m); sys.exit(1)
    n[0] += 1
import stagedrel as SD, cutrank as CR
src = open(os.path.join(HERE, "cutrank.py")).read()
ok("place_order" not in src and "POST" not in src and '"PUT"' not in src and "DELETE" not in src, "no order code in the file")
c = CR.load_cfg()
SPOT = 60000.0
T0 = dt.datetime(2026, 11, 27, 23, 31, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
legs = [dict(id=1, side="PE", sym="P-BTC-57000-281126", qty=0.30, entry=120.0, t=T0.isoformat()),
        dt.datetime and dict(id=2, side="PE", sym="P-BTC-57000-281126", qty=0.10, entry=140.0, t=(T0 + dt.timedelta(minutes=40)).isoformat()),
        dict(id=3, side="CE", sym="C-BTC-63000-281126", qty=0.40, entry=100.0, t=T0.isoformat())]
marks = {"P-BTC-57000-281126": 200.0, "C-BTC-63000-281126": 10.0}      # put in loss, call almost decayed
# cost is positive and grows with the mark
ok(CR.close_cost(c, SPOT, 10.0) > 0 and CR.close_cost(c, SPOT, 200.0) > CR.close_cost(c, SPOT, 10.0), "cost grows with mark")
tot = CR.total_margin(c, SPOT, legs, marks)
ok(tot > 0, "total margin positive")
# need 0 -> nothing cut
p0 = CR.plan_rank(c, SPOT, legs, marks, 0.0)
ok(p0["steps"] == [] and p0["freed"] == 0, "zero need cuts nothing")
# 50 % need: frees at least the need, whole contracts, never more than held
for sc in (0.25, 0.5, 1.0):
    need = tot * sc
    for name, p in (("A", CR.plan_fixed(c, SPOT, legs, marks, need)), ("B", CR.plan_rank(c, SPOT, legs, marks, need))):
        ok(p["freed"] >= need - 1.0 or p["short"] > 0, "%s %.2f frees the need or says short" % (name, sc))
        for s in p["steps"]:
            q = s[4]
            ok(abs(q / CR.C - round(q / CR.C)) < 1e-6 and q > 0, "%s whole contracts" % name)
    held = {l["id"]: l["qty"] for l in legs}
    used = {}
    for s in CR.plan_rank(c, SPOT, legs, marks, need)["steps"]:
        used[s[1]] = used.get(s[1], 0) + s[4]
    ok(all(used[k] <= held[k] + 1e-9 for k in used), "rank never cuts more than held (%.2f)" % sc)
# 100 % need takes every leg completely, nothing short
pr = CR.plan_rank(c, SPOT, legs, marks, tot * 0.9999)
ok(pr["short"] < 1.0, "rank can free almost everything")
# need above everything: short is reported
big = CR.plan_rank(c, SPOT, legs, marks, tot * 2)
ok(big["short"] > 0, "need larger than all margin -> short reported")
# rank order: the call almost decayed (cheap to close) is taken before the loss put when its ratio is higher
rk = CR.plan_rank(c, SPOT, legs, marks, tot * 0.1)
ok(len(rk["steps"]) >= 1 and rk["steps"][0][3] in ("PE", "CE"), "rank returns a first step")
ok(rk["steps"][0][3] == "CE", "cheap decayed call ranks first (best margin per cost)")
# determinism
ok(CR.plan_rank(c, SPOT, legs, marks, tot * 0.5)["steps"] == CR.plan_rank(c, SPOT, legs, marks, tot * 0.5)["steps"], "deterministic")
# scenarios give three rows with both plans
t2, res = CR.scenarios(c, SPOT, legs, marks)
ok(len(res) == 3 and all("A" in r and "B" in r for r in res) and abs(t2 - tot) < 1e-9, "scenarios shape")
print("SELFTEST CUTRANK PASSED (%d checks)" % n[0])
