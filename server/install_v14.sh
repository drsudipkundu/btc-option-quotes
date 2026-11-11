#!/bin/bash
# 11-Nov-2026: v14 = PAPER bot lv14 (v13 ladder + extra call split). Needs v13 installed. Run outside 23:25-00:05 IST.
# Restarts variantbot and ui only. Nightlive, ladderlive (live), ladshadow are NOT touched.
set -e
cd ~/deltabot
REF=${1:-main}
RAW=https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server
curl -fsSL $RAW/v14_patch.py -o /tmp/v14_patch.py
curl -fsSL $RAW/ladcall_v14_patch.py -o /tmp/ladcall_v14_patch.py
python3 /tmp/v14_patch.py ~/deltabot
python3 /tmp/ladcall_v14_patch.py ~/deltabot
./venv/bin/python -m py_compile variants.py control.py ui.py chartpage.py stratinfo.py ladderlive.py ladcall.py
./venv/bin/python variants.py --check | grep -E "lv14|lv13"
sudo systemctl restart variantbot
sudo systemctl restart ui
sleep 8
echo "variantbot: $(systemctl is-active variantbot)  ui: $(systemctl is-active ui)  nightlive: $(systemctl is-active nightlive)  ladderlive: $(systemctl is-active ladderlive)"
grep -a "lv14\|\[v14\]" logs/variants.log | tail -n 3
rm -f /tmp/v14_patch.py /tmp/ladcall_v14_patch.py
