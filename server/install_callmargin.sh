#!/bin/bash
# 10-Nov-2026: callmargin - READ-ONLY logger of the real margin Delta blocks on Ladderv9 (GET requests only).
# Adds 3 cron lines (server time is IST): every 5 min, every minute 17:30-17:49, and a summary email at 17:50.
# No service is restarted, no bot or setting is changed.
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/callmargin.py -o callmargin.py
./venv/bin/python -m py_compile callmargin.py
echo "--- reading now (not saved):"
./venv/bin/python callmargin.py --show
( crontab -l 2>/dev/null | grep -v callmargin.py
  echo "*/5 * * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python callmargin.py >> logs/callmargin.log 2>&1"
  echo "30-49 17 * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python callmargin.py >> logs/callmargin.log 2>&1"
  echo "50 17 * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python callmargin.py --summary >> logs/callmargin.log 2>&1" ) | crontab -
echo "cron: $(crontab -l | grep callmargin.py | wc -l) callmargin lines installed"
