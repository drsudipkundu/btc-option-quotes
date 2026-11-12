#!/bin/bash
# 12-Nov-2026: fillquality (READ-ONLY) - compares real night-sell fills with the recorded order book; one line per sale in logs/fillquality.csv.
# Cron 06:10 IST daily. Does not touch the bot, its settings or the guard limits.
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/fillquality.py -o fillquality.py
./venv/bin/python -m py_compile fillquality.py
echo "--- sales so far (nothing written yet):"
./venv/bin/python fillquality.py --show
( crontab -l 2>/dev/null | grep -v "fillquality.py"
  echo "10 6 * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python fillquality.py >> logs/fillquality.log 2>&1" ) | crontab -
echo "cron: $(crontab -l | grep -c fillquality.py) fillquality line installed"
