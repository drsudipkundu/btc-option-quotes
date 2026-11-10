#!/bin/bash
# 10-Nov-2026: nightwatch - READ-ONLY watchman for the night account (serverbot). GET requests only, AUTO_EXIT off.
# Adds 3 cron lines (server time is IST): every minute, a Telegram "alive" line at 17:40 and 23:40.
# No service is restarted, no bot or setting is changed. Needs state/telegram.env (written by Sudip).
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/nightwatch.py -o nightwatch.py
./venv/bin/python -m py_compile nightwatch.py
echo "--- reading now (nothing sent):"
./venv/bin/python nightwatch.py --show
( crontab -l 2>/dev/null | grep -v nightwatch.py
  echo "* * * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python nightwatch.py >> logs/nightwatch.log 2>&1"
  echo "40 17 * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python nightwatch.py --alive >> logs/nightwatch.log 2>&1"
  echo "40 23 * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python nightwatch.py --alive >> logs/nightwatch.log 2>&1" ) | crontab -
echo "cron: $(crontab -l | grep nightwatch.py | wc -l) nightwatch lines installed"
