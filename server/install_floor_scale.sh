#!/bin/bash
# 17-Nov-2026: capital floor per 0.01 base moves with BTC (both ways); formula counts v5's 4 units and the hedge. No bot is restarted.
set -e
REF=${1:-main}
cd ~/deltabot
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/floor_scale_patch.py -o floor_scale_patch.py
./venv/bin/python floor_scale_patch.py
restore() { [ -f sizecalc.py.bak1117 ] && cp sizecalc.py.bak1117 sizecalc.py; [ -f state/sizecalc.json.bak1117 ] && cp state/sizecalc.json.bak1117 state/sizecalc.json; echo "RESTORED - nothing changed"; exit 1; }
./venv/bin/python -m py_compile sizecalc.py || restore
[ -f state/sizecalc.json ] && cp state/sizecalc.json state/sizecalc.json.bak1117
./venv/bin/python - <<'P' || restore
import json, os
p = "state/sizecalc.json"
d = json.load(open(p)) if os.path.exists(p) else {}
d.update(safe_floor_inr=33000, safe_floor_ref_btc=82000)
json.dump(d, open(p, "w")); print("sizecalc.json:", d)
import sizecalc as SC
S = SC.settings(); ind = dict(hv14=0.30, atr=2600.0)
a, b, c = (SC.safe_balance(x, ind, S) for x in (64000.0, 82000.0, 100000.0))
assert abs(b["floor"] * S["usd_inr"] - 33000) < 1 and abs(a["floor"] / b["floor"] - 64 / 82) < 1e-9 and abs(c["floor"] / b["floor"] - 100 / 82) < 1e-9
assert all(x["safe"] >= x["floor"] - 1e-9 and x["safe"] >= x["formula"] - 1e-9 for x in (a, b, c))
for x, px in ((a, 64000), (b, 82000), (c, 100000)):
    print("BTC %6d: floor Rs %6.0f | formula Rs %6.0f (%d units, hedge %s) -> keep Rs %6.0f per 0.01" % (
        px, x["floor"] * S["usd_inr"], x["formula"] * S["usd_inr"], x["units"], ("%.0f %%" % (x["wing"] * 100)) if x["wing"] else "off", x["safe"] * S["usd_inr"]))
P
./venv/bin/python autosize.py --show | cut -c1-300
echo "FLOOR SCALE INSTALL DONE"
