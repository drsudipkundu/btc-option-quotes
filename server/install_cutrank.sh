#!/bin/bash
# 27-Nov-2026 c29: CUT RANKING, PAPER ONLY (cutrank.py). READ-ONLY: GET requests only, never an order, never a money move, never a setting change;
# the night bot is not touched or restarted. Adds ONE cron line (marker "# cutrank-c29", every 30 minutes, does nothing unless a night position is open).
# Remove it with: crontab -l | grep -v cutrank-c29 | crontab -
# Needs c18 (stagedrel.py) on the server. Safe at any hour. Self-test first; nothing is scheduled if it fails.
set -e
REF=${1:-main}
cd ~/deltabot
[ -f stagedrel.py ] || { echo "stagedrel.py (c18) missing - nothing done"; exit 1; }
for f in cutrank.py selftest_cutrank.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python -m py_compile cutrank.py
./venv/bin/python selftest_cutrank.py > logs/selftest_cutrank.txt 2>&1 || { tail -n 15 logs/selftest_cutrank.txt; echo "SELF-TEST FAILED - nothing scheduled"; exit 1; }
grep -E "PASSED" logs/selftest_cutrank.txt
L="*/30 * * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python cutrank.py >> logs/cutrank.log 2>&1 # cutrank-c29"
( crontab -l 2>/dev/null | grep -v "cutrank-c29" ; echo "$L" ) | crontab -
crontab -l | grep -c "cutrank-c29"
echo "--- preview (read only, not logged):"
./venv/bin/python cutrank.py --show 2>&1 | head -n 8 | cut -c1-300
echo "CUTRANK INSTALL DONE"
