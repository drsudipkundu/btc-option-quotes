#!/bin/bash
# 27-Nov-2026 c30: WHAT-IF for hand-closed legs, REPORT ONLY (whatif.py). Reads the trade log and public Delta candles (GET only), never places an order, never changes a setting;
# the night bot is not touched or restarted. Adds ONE cron line (marker "# whatif-c30", 17:45 IST daily). Remove: crontab -l | grep -v whatif-c30 | crontab -
# Safe at any hour. Self-test first; nothing is scheduled if it fails. Runs once now to fill the nights already settled.
set -e
REF=${1:-main}
cd ~/deltabot
for f in whatif.py selftest_whatif.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python -m py_compile whatif.py
./venv/bin/python selftest_whatif.py > logs/selftest_whatif.txt 2>&1 || { tail -n 15 logs/selftest_whatif.txt; echo "SELF-TEST FAILED - nothing scheduled"; exit 1; }
grep -E "PASSED" logs/selftest_whatif.txt
L="45 17 * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python whatif.py >> logs/whatif.log 2>&1 # whatif-c30"
( crontab -l 2>/dev/null | grep -v "whatif-c30" ; echo "$L" ) | crontab -
crontab -l | grep -c "whatif-c30"
echo "--- run now:"
./venv/bin/python whatif.py 2>&1 | cut -c1-200 | tail -n 12
echo "WHATIF INSTALL DONE"
