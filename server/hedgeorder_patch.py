#!/usr/bin/env python3
"""hedgeorder_patch (c10, 25-Nov-2026, Sudip 00:15 / 00:19: "hedge rule - in/out checking, if one side failed shifting to the other must continue").
Order in which far options (hedges) are tried for a sold option, put AND call side:
   1. the usual target (first strike >= wing % of BTC beyond the sold strike) - tested strike stays first choice
   2. then nearest first, alternating, IN before OUT: 1 in, 1 out, 2 in, 2 out ...
      (in = between the sold strike and the target; out = beyond the target)
 The price ceiling (puts 30 %, calls 50 % of the sale price), capped-strike skip (c03) and the retries are unchanged: a candidate that is too
 dear / refused / has no offer is skipped and the next one in the order is tried, so a failure on one side of the order moves on to the other.
 Before this patch the order was: target, every strike OUT (up to 5), and only then the strikes IN.
 NOT included (parked for the 27-Nov review): the BTC-future last resort. Replaces only the last line of _wing_cands. Must match once, else nothing
 is written. Backup nightlive.py.bak1125h"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
P = os.path.join(H, "nightlive.py")
src = open(P, encoding="utf-8").read()
OLD = "        return far[:n + 1] + near[:n + 1]\n"
NEW = '''        # 25-Nov-2026 c10 hedge rule: target first, then 1 in, 1 out, 2 in, 2 out ... (in before out)
        far, near = far[:n + 1], near[:n + 1]
        order = far[:1]
        for i in range(max(len(near), len(far) - 1)):
            if i < len(near):
                order.append(near[i])
            if i + 1 < len(far):
                order.append(far[i + 1])
        return order
'''
if "c10 hedge rule" in src:
    print("already installed"); sys.exit(0)
if src.count(OLD) != 1:
    print("ANCHOR NOT FOUND exactly once - NOTHING CHANGED"); sys.exit(1)
shutil.copy(P, os.path.join(H, "nightlive.py.bak1125h"))
open(P, "w", encoding="utf-8").write(src.replace(OLD, NEW))
print("hedge order patch written")
