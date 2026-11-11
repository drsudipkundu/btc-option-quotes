#!/bin/bash
# 11-Nov-2026: decay buy-back for the ladder calls (lv15 only): resting buy-back at 97 % decay once BTC is 2 % above the price at the sale.
# Needs v15 installed (ladcall_v15_patch). Run outside 23:25-00:05 IST. Restarts variantbot only; nightlive, ladderlive, ui are NOT touched.
set -e
cd ~/deltabot
REF=${1:-main}
RAW=https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server
curl -fsSL $RAW/ladcall_dx_patch.py -o ladcall_dx_patch.py
python3 ladcall_dx_patch.py ~/deltabot
./venv/bin/python -m py_compile ladcall.py
python3 - <<'PY'
import json, os
f = "call_settings.json"
d = json.load(open(f)) if os.path.exists(f) else {}
lv = d.setdefault("lv15", {"xmul": 5, "xmax_btc": 0.3, "split_n": 2})
lv.setdefault("dx_arm", 0.02); lv.setdefault("dx_level", 0.97)
json.dump(d, open(f, "w")); print(open(f).read())
PY
sudo systemctl restart variantbot
sleep 8
echo "variantbot: $(systemctl is-active variantbot)  nightlive: $(systemctl is-active nightlive)  ladderlive: $(systemctl is-active ladderlive)"
