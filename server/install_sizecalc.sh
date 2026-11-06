#!/bin/bash
# 6-Nov-2026: night-sell size calculator, PHASE 1 (paper only: reads the balance, logs + emails the size it WOULD choose,
# never places orders, never changes the live size). Adds a cron line at 23:20 IST (server time is IST). No service restarted.
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/sizecalc.py -o sizecalc.py
./venv/bin/python -m py_compile sizecalc.py
echo "--- calculation now (no email, no log):"
./venv/bin/python sizecalc.py --show
( crontab -l 2>/dev/null | grep -v sizecalc.py; echo "20 23 * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python sizecalc.py >> logs/sizecalc.log 2>&1" ) | crontab -
echo "cron: $(crontab -l | grep sizecalc.py)"
