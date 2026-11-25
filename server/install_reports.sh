#!/bin/bash
# 25-Nov-2026 c16: scheduled Telegram + Gmail reports (22:00 plan, 23:33 decision, 23:50 position, 07:00 and 17:22 status, event status after changes).
# READ-ONLY: no order, no setting, the bot is not touched or restarted. Adds 6 cron lines (marker "# reports-c16"); remove them with: crontab -l | grep -v reports-c16 | crontab -
# Safe at any hour (no order, no bot restart). Self-test first; nothing is scheduled if it fails.
set -e
REF=${1:-main}
cd ~/deltabot
for f in reports.py selftest_reports.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python -m py_compile reports.py
./venv/bin/python selftest_reports.py > logs/selftest_reports.txt 2>&1 || { tail -n 15 logs/selftest_reports.txt; echo "SELF-TEST FAILED - nothing scheduled"; exit 1; }
grep -E "PASSED" logs/selftest_reports.txt
P="cd $HOME/deltabot && $HOME/deltabot/venv/bin/python reports.py"
L="$(cat <<EOF
0 22 * * * $P plan >> logs/reports.log 2>&1 # reports-c16
33 23 * * * $P decision >> logs/reports.log 2>&1 # reports-c16
50 23 * * * $P position >> logs/reports.log 2>&1 # reports-c16
0 7 * * * $P status >> logs/reports.log 2>&1 # reports-c16
22 17 * * * $P status >> logs/reports.log 2>&1 # reports-c16
* * * * * $P watch >> logs/reports.log 2>&1 # reports-c16
EOF
)"
( crontab -l 2>/dev/null | grep -v "reports-c16" ; echo "$L" ) | crontab -
crontab -l | grep -c "reports-c16"
echo "--- live preview of the status report (read only, not sent):"
./venv/bin/python reports.py show status | head -n 14 | cut -c1-220
echo "REPORTS INSTALL DONE"
