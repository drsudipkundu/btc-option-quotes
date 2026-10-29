#!/bin/bash
# 29-Oct-2026: add slope-half paper copies v4A-CG-SL / v5A-CG-SL to the night bot (old v4A/v5A keep running).
# Backups *.bak10 are made first. Paper only; no keys or orders touched.
set -e
cd ~/deltabot
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/main/server/night_sl_patch.py -o /tmp/night_sl_patch.py
python3 /tmp/night_sl_patch.py ~/deltabot
./venv/bin/python -m py_compile nightlogic.py nightbot.py control.py ui.py
./venv/bin/python nightbot.py --check | tail -n 12
sudo systemctl restart nightbot ui
sleep 4
echo "nightbot: $(systemctl is-active nightbot)  ui: $(systemctl is-active ui)"
tail -n 3 logs/night.log
