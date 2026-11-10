#!/bin/bash
# 10-Nov-2026: margin truth log for the NIGHT account (serverbot): callmargin.py with CM_ACCT=serverbot. READ-ONLY (GET only).
# Cron lines (server time is IST): every 5 min, and every minute 23:30-23:59 (the night sale window). Logs to logs/callmargin_serverbot.csv.
set -e
cd ~/deltabot
REF=${1:-main}
for f in callmargin.py nightwatch.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; ./venv/bin/python -m py_compile $f; done
echo "--- night account reading (not saved):"
CM_ACCT=serverbot ./venv/bin/python callmargin.py --show | cut -c1-300
( crontab -l 2>/dev/null | grep -v "CM_ACCT=serverbot"
  echo "*/5 * * * * cd $HOME/deltabot && CM_ACCT=serverbot $HOME/deltabot/venv/bin/python callmargin.py >> logs/callmargin_serverbot.log 2>&1"
  echo "30-59 23 * * * cd $HOME/deltabot && CM_ACCT=serverbot $HOME/deltabot/venv/bin/python callmargin.py >> logs/callmargin_serverbot.log 2>&1" ) | crontab -
echo "cron: $(crontab -l | grep -c 'CM_ACCT=serverbot') night-margin lines installed"
