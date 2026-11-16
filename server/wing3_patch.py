#!/usr/bin/env python3
"""wing3_patch (16-Nov-2026). Run in ~/deltabot after wing2_patch. autosize.py only.
While a ceiling is set, every 23:22 run also sets the guard size limits to fit tonight's base with the hedge:
  per order = 3 x base (the biggest single sale), open total = 8 x base (4 units sold + 4 bought), never below 0.05 / 0.15.
So when Sudip adds money the base AND the limits follow by themselves. Daily loss limit is not touched.
Every edit must match exactly once, otherwise NOTHING is written. Backup: autosize.py.bak1116w3"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
EDITS = [
 ('''def decide(balance_usd''', '''def limits_for(base):
    """guard limits that fit this base with the always-on hedge"""
    return dict(max_order_btc=round(max(0.05, 3 * base), 3), max_open_btc=round(max(0.15, 8 * base), 3))


def sync_limits(base):
    p = os.path.join(HOME, "state", "limits.json")
    cur = jload(p)
    new = dict(cur); new.update(limits_for(base))
    if new != cur:
        jsave(p, new)
        return "size limits now %.2f per order / %.2f open" % (new["max_order_btc"], new["max_open_btc"])
    return ""


def decide(balance_usd'''),
 ('''    st["max_base"] = D["max_base"]; st["ts"] = now; st.setdefault("on", True)''',
  '''    if st.get("ceiling") and now >= st.get("ceiling_from_ts", 0):
        try:
            lm = sync_limits(float(jload(CFG_F).get("base", live_base)))
            if lm:
                msg = (msg + " | " if msg else "AUTO SIZE: ") + lm
        except Exception as e:
            msg = (msg or "AUTO SIZE:") + " (size limits NOT updated: %s)" % e
    st["max_base"] = D["max_base"]; st["ts"] = now; st.setdefault("on", True)'''),
]
p = os.path.join(H, "autosize.py"); s = open(p).read()
if "sync_limits" in s:
    print("already patched"); sys.exit(0)
if "ceiling_from_ts" not in s:
    print("STOP: wing2_patch is not installed. NOTHING WRITTEN"); sys.exit(1)
for old, new in EDITS:
    if s.count(old) != 1:
        print("STOP: expected one match, found %d for: %s\nNOTHING WRITTEN" % (s.count(old), old[:80])); sys.exit(1)
    s = s.replace(old, new)
shutil.copy2(p, p + ".bak1116w3"); open(p + ".tmp", "w").write(s); os.replace(p + ".tmp", p)
print("WING3 PATCH DONE")
