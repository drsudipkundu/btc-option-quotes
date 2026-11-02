#!/bin/bash
# 2-Nov-2026: v13 hyperdynamic ladder = PAPER bot "lv13" in variantbot + v13 section (13 copies) in the ladder shadow fleet.
# Night bots (nightbot, nightlive, shadowbot) are NOT touched. ladderlive is patched (lv13 key) but NOT restarted.
# Run outside 23:25-00:05 IST.
set -e
cd ~/deltabot
REF=${1:-main}
RAW=https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server
curl -fsSL $RAW/v13_patch.py -o /tmp/v13_patch.py
curl -fsSL $RAW/ladshadow.py -o /tmp/ladshadow.py
curl -fsSL $RAW/healthnav.py -o /tmp/healthnav.py
python3 /tmp/v13_patch.py ~/deltabot
cp -n ladshadow.py ladshadow.py.bak_v13 || true
cp -n healthnav.py healthnav.py.bak_v13 || true
cp /tmp/ladshadow.py ladshadow.py
cp /tmp/healthnav.py healthnav.py
./venv/bin/python -m py_compile variants.py control.py ui.py chartpage.py stratinfo.py ladderlive.py ladshadow.py healthnav.py
./venv/bin/python variants.py --check | grep -E "lv13|lv12|lv11|lv10"
./venv/bin/python ladshadow.py --check | grep -E "v13|copies"
sudo systemctl restart variantbot
sudo systemctl restart ladshadow
sudo systemctl restart ui
sleep 8
echo "variantbot: $(systemctl is-active variantbot)  ladshadow: $(systemctl is-active ladshadow)  ui: $(systemctl is-active ui)  nightlive: $(systemctl is-active nightlive)  ladderlive: $(systemctl is-active ladderlive)"
grep -a "lv13\|\[v13\]" logs/variants.log | tail -n 3
tail -n 2 logs/ladshadow.log
rm -f /tmp/v13_patch.py /tmp/ladshadow.py /tmp/healthnav.py
