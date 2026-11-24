#!/usr/bin/env python3
"""Offline self-test of the upgraded REPORT-ONLY sweep (24-Nov-2026). No network, no keys, nothing is moved.
Checks the serverbot-multiple / main-account-pocket planner on Sudip's worked cases, that nothing scales with a fixed rupee step,
and that the whole report runs against a pretend exchange and contains no transfer call."""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_report as SR

C = dict(SR.CFG)
ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1; print("  ok   ", name)
    else: bad += 1; print("  FAIL ", name, extra)

STEP = 43800.0
def plan(n, pocket, step=STEP, flat=True, left=None, c=C):
    return SR.pocket_plan(n * step, step, pocket, c, flat, left)

print("planner cases")
p = plan(16.7, 30000)                                    # Sudip's example: 16.7 steps, pocket Rs 25,000
check("16.7 steps: top up to 17 + cushion", abs(p["move_inr"] - (17.04 - 16.7) * STEP) < 1 and p["base_after"] == 0.17, p)
p = plan(16.7, 5000)                                     # pocket at its floor
check("pocket at floor: nothing goes to serverbot", p["move_inr"] == 0 and "pocket" in p["why"], p)
p = plan(16.7, 12000)                                    # Rs 7,000 above floor, need ~Rs 14,900
check("pocket too small: no partial top-up", p["move_inr"] == 0 and "add money" in p["why"], p)
p = plan(16.3, 10000)                                    # leftover goes back to the pocket
check("16.3 steps: leftover back to pocket", abs(p["move_inr"] + (16.3 - 16.04) * STEP) < 1, p)
p = plan(16.3, 20000)                                    # pocket room only Rs 5,000
check("pull-back limited by the pocket target", abs(p["move_inr"] + 10000) < 1, p)
p = plan(16.3, 30000)
check("pocket full: leftover stays in serverbot", p["move_inr"] == 0 and "target" in p["why"], p)
for n in (16.41, 16.45, 16.49):
    check("dead band %.2f: no move" % n, plan(n, 30000)["move_inr"] == 0)
check("exactly 0.5: top-up (worst case needs 0.54 step = Rs 23,652)", plan(16.5, 30000)["move_inr"] > 0 and plan(16.5, 25000)["move_inr"] == 0)
check("exactly 0.4: pull-back", plan(16.4, 10000)["move_inr"] < 0)
p = plan(16.02, 10000)
check("inside cushion: small note, no tiny move", p["move_inr"] == 0 and "small BTC rise" in p["why"], p)
check("not flat: no move", plan(16.7, 30000, flat=False)["move_inr"] == 0)
check("daily cap respected", plan(16.7, 30000, left=10000)["move_inr"] == 0)
check("no move below 0.1 step", plan(16.97, 25000)["move_inr"] == 0 or plan(16.97, 25000)["move_inr"] >= 0.1 * STEP)

print("nothing fixed to a rupee step (follows BTC)")
for step in (30000.0, 43800.0, 60000.0):
    a, b = SR.pocket_plan(16.7 * step, step, 10 ** 9, C, True, 10 ** 9), SR.pocket_plan(16.3 * step, step, 0, C, True, 10 ** 9)
    check("step %.0f scales" % step, abs(a["move_inr"] / step - 0.34) < 1e-6 and abs(b["move_inr"] / step + 0.26) < 1e-6, (a, b))
c2 = dict(C, pocket_floor_inr=0.0, pocket_target_inr=10 ** 9)
check("same balance, bigger step (BTC up): different fraction", abs(SR.pocket_plan(731460.0, 48180.0, 10 ** 6, c2, True, 10 ** 9)["frac"] - 0.18) < 0.01)

print("whole report against a pretend exchange")
class Pub:
    def _http(self, m, path): return {"result": {"spot_price": "63000", "mark_price": "63000", "product_id": 27}}
class Live:
    def __init__(self, name): self.name = name
    def _p(self, m, path, params=None, body=None):
        assert m == "GET", "the report must only READ (got %s %s)" % (m, path)
        if "wallet/balances" in path:
            usd = {"ladder9": 14.4e5 / 85, "serverbot": 7.3e5 / 85, "main": 20000 / 85}[self.name]
            return {"result": [{"asset_symbol": "USD", "balance": str(usd), "available_balance": str(usd), "blocked_margin": "0"}]}
        return {"result": []}
d = SR.compute(C, Live, Pub)
msg, det = SR.message(d["c"], d), SR.detail(d["c"], d)
print("\n".join("    | " + l for l in msg.splitlines()))
check("report has multiple + pocket lines", "SERVERBOT MULTIPLE" in msg and "POCKET WOULD MOVE" in msg and "POCKET (main account)" in msg)
check("small pocket target gets a warning", "WARNING" in SR.message(dict(d["c"], pocket_target_inr=20000), dict(d, c=dict(d["c"], pocket_target_inr=20000))))
check("details list the multiple rules", "Multiple rules" in det and "REPORT ONLY" in det)
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_report.py")).read()
check("file has no transfer call", "sub_account_balance_transfer" not in src and '"POST"' not in src and "'POST'" not in src)
print("\n%d ok, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
