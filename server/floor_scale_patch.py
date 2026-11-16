#!/usr/bin/env python3
"""floor_scale_patch (17-Nov-2026, Sudip 16-Nov 23:10 "want floor move both ways"). Run in ~/deltabot. sizecalc.py only.
Capital to keep per 0.01 BTC base = the larger of (a) the nightly formula and (b) the floor. Changes:
 1. The floor moves with BTC: floor = safe_floor_inr x BTC price / safe_floor_ref_btc  (Rs 33,000 was derived at BTC 82,000,
    i.e. about 46 % of the value of 0.01 BTC). Off (fixed floor, as before) while safe_floor_ref_btc is 0.
 2. The formula counts the units the LIVE rule can really sell on its biggest night: 4 for v5, 3 for v4 (it assumed 3).
 3. With the always-on hedge ON, the formula uses the hedged loss: the gap between the sold strike and the far option (wing %)
    instead of the crash-guard gap. Hedge off -> the crash-guard formula as before.
Every edit must match exactly once, otherwise nothing is written. Backup sizecalc.py.bak1117"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
EDITS = [
 ('''    safe_floor_inr=30000.0,''', '''    safe_floor_ref_btc=0.0,             # 17-Nov-2026: BTC price at which safe_floor_inr was derived; > 0 = the floor moves with BTC
    safe_floor_inr=30000.0,'''),
 ('''    n = S["v4_max_mult"] * 0.01 * price                       # notional sold per 0.01 base at 3 x
    before = n * (max(0.0, trig - dist) + S["time_value_frac"])
    cap = n * max(0.0, (1 - dist) - (1 - S["ins_beyond"]) * (1 - trig))
    ins, mar = n * S["ins_cost_frac"], n * S["margin_stress_frac"]
    safe = max(cap + ins + mar, S.get("safe_floor_inr", 0.0) / S["usd_inr"])  # never below the Rs floor''',
  '''    lc = live_cfg()
    units = 4.0 if lc.get("rule") == "v5asl" else S["v4_max_mult"]      # biggest night of the live rule
    wing = float(lc.get("wing") or 0)
    n = units * 0.01 * price                                  # notional sold per 0.01 base on the biggest night
    before = n * (max(0.0, trig - dist) + S["time_value_frac"])
    if wing > 0:                                              # always-on hedge: loss is capped at the gap to the far option
        cap = n * wing
    else:
        cap = n * max(0.0, (1 - dist) - (1 - S["ins_beyond"]) * (1 - trig))
    ins, mar = n * S["ins_cost_frac"], n * S["margin_stress_frac"]
    floor = S.get("safe_floor_inr", 0.0) / S["usd_inr"]
    if S.get("safe_floor_ref_btc", 0) > 0:
        floor *= price / S["safe_floor_ref_btc"]              # the floor moves with BTC, both ways
    safe = max(cap + ins + mar, floor)                        # never below the floor'''),
 ('''def safe_balance(price, ind, S):''', '''def live_cfg():
    try:
        return json.load(open(os.path.join(HOME, "state", "night_live_cfg.json")))
    except Exception:
        return {}


def safe_balance(price, ind, S):'''),
 ('''                safe=safe, hv14=hv14, atr=atr)''', '''                safe=safe, hv14=hv14, atr=atr, floor=floor, formula=cap + ins + mar, units=units, wing=wing)'''),
]
p = os.path.join(H, "sizecalc.py"); s = open(p).read()
if "safe_floor_ref_btc" in s:
    print("already patched"); sys.exit(0)
for old, new in EDITS:
    if s.count(old) != 1:
        print("STOP: expected one match, found %d for: %s\nNOTHING WRITTEN" % (s.count(old), old[:70])); sys.exit(1)
    s = s.replace(old, new)
shutil.copy2(p, p + ".bak1117"); open(p + ".tmp", "w").write(s); os.replace(p + ".tmp", p)
print("FLOOR SCALE PATCH DONE (sizecalc.py)")
