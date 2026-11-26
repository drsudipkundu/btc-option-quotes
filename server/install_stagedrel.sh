#!/bin/bash
# 26-Nov-2026 c18: EMERGENCY STAGED MARGIN RELEASE, REPORT ONLY (stagedrel.py). READ-ONLY: it sends GET requests only, never places an order,
# never moves money, never changes a setting; the night bot is not touched or restarted. Adds ONE cron line (marker "# stagedrel-c18", every 2 minutes);
# remove it with: crontab -l | grep -v stagedrel-c18 | crontab -
# Safe at any hour (no order, no bot restart). Self-test first; nothing is scheduled if it fails.
set -e
REF=${1:-main}
cd ~/deltabot
for f in stagedrel.py selftest_stagedrel.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python -m py_compile stagedrel.py
./venv/bin/python selftest_stagedrel.py > logs/selftest_stagedrel.txt 2>&1 || { tail -n 15 logs/selftest_stagedrel.txt; echo "SELF-TEST FAILED - nothing scheduled"; exit 1; }
grep -E "PASSED" logs/selftest_stagedrel.txt
L="*/2 * * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python stagedrel.py >> logs/stagedrel.log 2>&1 # stagedrel-c18"
( crontab -l 2>/dev/null | grep -v "stagedrel-c18" ; echo "$L" ) | crontab -
crontab -l | grep -c "stagedrel-c18"
echo "--- live preview (read only, not sent):"
./venv/bin/python stagedrel.py --show 2>&1 | head -n 14 | cut -c1-240
echo "STAGEDREL INSTALL DONE"
