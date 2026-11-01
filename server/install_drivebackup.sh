#!/bin/bash
# 1-Nov-2026: daily shadow-fleet backup mail (for the Drive copy). Adds one cron line at 18:05 IST. No bot is restarted.
set -e
C=${1:?commit}
cd ~/deltabot
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$C/server/drivebackup.py -o drivebackup.py
venv/bin/python -m py_compile drivebackup.py
venv/bin/python drivebackup.py --dry
L="5 18 * * * cd $HOME/deltabot && venv/bin/python drivebackup.py >> logs/drivebackup.log 2>&1"
( crontab -l 2>/dev/null | grep -v drivebackup.py ; echo "$L" ) | crontab -
crontab -l | grep drivebackup
venv/bin/python drivebackup.py
echo BACKUP INSTALL DONE
