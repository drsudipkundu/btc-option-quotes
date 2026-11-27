#!/bin/bash
# 27-Nov-2026 c33: FLAG RANK paper log (flagrank.py). Reads three files the night seller already writes; never places an order, never calls the exchange,
# never changes a setting or a state file; the night bot is not touched or restarted. Adds ONE cron line (marker "# flagrank-c33", 23:50 IST daily).
# Remove: crontab -l | grep -v flagrank-c33 | crontab -     Self-test first; nothing is scheduled if it fails. Runs once now to fill past nights.
set -e
REF=${1:-main}
cd ~/deltabot
for f in flagrank.py selftest_flagrank.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python -m py_compile flagrank.py
./venv/bin/python selftest_flagrank.py > logs/selftest_flagrank.txt 2>&1 || { tail -n 15 logs/selftest_flagrank.txt; echo "SELF-TEST FAILED - nothing scheduled"; exit 1; }
grep -E "PASSED" logs/selftest_flagrank.txt
L="50 23 * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python flagrank.py >> logs/flagrank.log 2>&1 # flagrank-c33"
( crontab -l 2>/dev/null | grep -v "flagrank-c33" ; echo "$L" ) | crontab -
crontab -l | grep -c "flagrank-c33"
echo "--- run now:"
./venv/bin/python flagrank.py 2>&1 | tail -n 2
./venv/bin/python flagrank.py report 2>&1 | cut -c1-160 | tail -n 14
echo "FLAGRANK INSTALL DONE"
