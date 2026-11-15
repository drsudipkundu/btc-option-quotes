#!/bin/bash
# 15-Nov-2026: edgecheck.py - READ-ONLY monthly "is the night sell still earning what the test says" report.
# No orders, no API key, no change to any bot file. Cron: 1st of every month 09:00 IST. Sends the first report now.
set -e
REF=${1:-main}
cd ~/deltabot
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/edgecheck.py -o edgecheck.py.new
./venv/bin/python -m py_compile edgecheck.py.new && mv edgecheck.py.new edgecheck.py
./venv/bin/python edgecheck.py
LINE='0 9 1 * * cd /home/ubuntu/deltabot && /home/ubuntu/deltabot/venv/bin/python edgecheck.py >> logs/edgecheck.log 2>&1'
(crontab -l 2>/dev/null | grep -v 'edgecheck.py'; echo "$LINE") | crontab -
echo "cron: $(crontab -l | grep -c edgecheck.py) edgecheck line | nightlive: $(systemctl is-active nightlive)"
echo "EDGECHECK INSTALL DONE"
