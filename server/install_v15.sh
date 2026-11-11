#!/bin/bash
# 11-Nov-2026: v15 = PAPER bot lv15 (v13 ladder + extra call split). Needs v13 installed. Run outside 23:25-00:05 IST.
# Restarts variantbot and ui only. Nightlive, ladderlive (live), ladshadow are NOT touched.
set -e
cd ~/deltabot
REF=${1:-main}
RAW=https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server
curl -fsSL $RAW/v15_patch.py -o /tmp/v15_patch.py
curl -fsSL $RAW/ladcall_v15_patch.py -o /tmp/ladcall_v15_patch.py
python3 /tmp/v15_patch.py ~/deltabot
python3 /tmp/ladcall_v15_patch.py ~/deltabot
[ -f call_settings.json ] || echo '{"lv15": {"xmul": 5, "xmax_btc": 0.3, "split_n": 2}}' > call_settings.json
./venv/bin/python -m py_compile variants.py control.py ui.py chartpage.py stratinfo.py ladderlive.py ladcall.py
./venv/bin/python variants.py --check | grep -E "lv15|lv13"
sudo systemctl restart variantbot
sudo systemctl restart ui
sleep 8
echo "variantbot: $(systemctl is-active variantbot)  ui: $(systemctl is-active ui)  nightlive: $(systemctl is-active nightlive)  ladderlive: $(systemctl is-active ladderlive)"
grep -a "lv15\|\[v15\]" logs/variants.log | tail -n 3
rm -f /tmp/v15_patch.py /tmp/ladcall_v15_patch.py
