#!/bin/bash
# 2-Nov-2026: per-strategy brake (max BTC held) settable from the control page. Restarts deltabot (v9 paper), variantbot, ui.
# ladderlive is patched but NOT restarted (disarmed; picks it up at its next restart). Night bots untouched. Run outside 23:25-00:05 IST.
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/brake_patch.py -o /tmp/brake_patch.py
python3 /tmp/brake_patch.py ~/deltabot
./venv/bin/python -m py_compile control.py bot.py variants.py ui.py ladderlive.py
./venv/bin/python -c "import sys; sys.path.insert(0,'.'); import control; print('brakes:', {k: control.brake_for(k) for k in control.NAMES if k.startswith('l')})"
sudo systemctl restart deltabot
sudo systemctl restart variantbot
sudo systemctl restart ui
sleep 8
echo "deltabot: $(systemctl is-active deltabot)  variantbot: $(systemctl is-active variantbot)  ui: $(systemctl is-active ui)  ladderlive: $(systemctl is-active ladderlive)  nightlive: $(systemctl is-active nightlive)"
tail -n 2 logs/bot.log; tail -n 2 logs/variants.log
rm -f /tmp/brake_patch.py
