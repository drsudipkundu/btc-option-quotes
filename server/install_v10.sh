#!/bin/bash
# 31-Oct-2026: v10 nested ladder as a PAPER bot "lv10" inside variantbot (next to lv11 / lv12).
# Night bots (nightbot, nightlive, shadowbot) are NOT touched. Run outside 23:25-00:05 IST.
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/v10_patch.py -o /tmp/v10_patch.py
python3 /tmp/v10_patch.py ~/deltabot
./venv/bin/python -m py_compile variants.py control.py ui.py chartpage.py
./venv/bin/python variants.py --check
sudo systemctl restart variantbot
sudo systemctl restart ui
sleep 5
echo "variantbot: $(systemctl is-active variantbot)  ui: $(systemctl is-active ui)  nightlive: $(systemctl is-active nightlive)"
grep "\[lv10\]\|lv10" logs/variants.log | tail -n 3
rm -f /tmp/v10_patch.py
