#!/bin/bash
# 11-Nov-2026: nightwatch Telegram commands (/status /result /pause /resume /help, only from Sudip's chat) + daily result message at 17:36 IST.
# /pause and /resume do exactly what the control-page Pause button does (state paused/running for "nlive"). No order is placed by any command.
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/nightwatch.py -o nightwatch.py
./venv/bin/python -m py_compile nightwatch.py
echo "--- reading now (nothing sent):"
./venv/bin/python nightwatch.py --show
( crontab -l 2>/dev/null | grep -v "nightwatch.py --daily"
  echo "36 17 * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python nightwatch.py --daily >> logs/nightwatch.log 2>&1" ) | crontab -
echo "cron: $(crontab -l | grep -c nightwatch.py) nightwatch lines installed"
