#!/bin/bash
# 23-Nov-2026: installs the REPORT-ONLY daily balance sweep (sweep_report.py). It only reads balances/positions and sends a Telegram message.
# It cannot move money or place orders. Adds one cron line: 18:15 IST daily. Runs once now in print-only mode so you see the first numbers.
set -eo pipefail
REF="${1:-main}"
cd ~/deltabot
curl -fsSL "https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/sweep_report.py" -o sweep_report.py.new
./venv/bin/python -m py_compile sweep_report.py.new
mv sweep_report.py.new sweep_report.py
LINE="15 18 * * * cd ~/deltabot && ./venv/bin/python sweep_report.py >> logs/sweep_report.out 2>&1"
( crontab -l 2>/dev/null | grep -v "sweep_report.py" ; echo "$LINE" ) | crontab -
echo "cron installed (server clock must be IST):"; crontab -l | grep sweep_report
echo "--- first look (print only, no Telegram):"
./venv/bin/python sweep_report.py --show
