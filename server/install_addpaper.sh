#!/bin/bash
# 27-Nov-2026 c32: ADD PAPER LOGGER (addpaper.py). Public Delta data only (GET), reads the live seller's state file read-only, never an order, never a setting;
# the night bot is not touched or restarted. Adds ONE cron line (marker "# addpaper-c32", every 2 minutes). Remove: crontab -l | grep -v addpaper-c32 | crontab -
# Safe at any hour. Self-test first; nothing is scheduled if it fails.
set -e
REF=${1:-main}
cd ~/deltabot
for f in addpaper.py selftest_addpaper.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
python3 -m py_compile addpaper.py
python3 selftest_addpaper.py > logs/selftest_addpaper.txt 2>&1 || { tail -n 15 logs/selftest_addpaper.txt; echo "SELF-TEST FAILED - nothing scheduled"; exit 1; }
grep -E "PASSED" logs/selftest_addpaper.txt
L="*/2 * * * * cd $HOME/deltabot && /usr/bin/python3 addpaper.py >> logs/addpaper.log 2>&1 # addpaper-c32"
( crontab -l 2>/dev/null | grep -v "addpaper-c32" ; echo "$L" ) | crontab -
crontab -l | grep -c "addpaper-c32"
python3 -c "
import addpaper as A, time
e=A.next_expiry(time.time()); ch=A.chain(e); x=float(A.get('/v2/tickers/BTCUSD')['mark_price'])
k=A.nearest(ch,'C',x*1.025); q=ch[('C',k)]
print('live check: spot %.0f, %d options, call %d bid %s ask %s' % (x, len(ch), k, q['bid'], q['ask']))"
python3 addpaper.py; echo "ADDPAPER INSTALL DONE"
