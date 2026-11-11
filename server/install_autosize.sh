#!/bin/bash
# 11-Nov-2026: night-sell AUTO SIZE CUT. Adds one cron line at 23:22 IST (server time is IST). Places no orders.
# It can lower the night base / pause the sale and restart the nightlive service - only when the account is flat.
# Also refreshes sizecalc.py (Rs 45,000 floor). Nothing is restarted by this install.
set -e
cd ~/deltabot
REF=${1:-main}
for f in autosize.py sizecalc.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o /tmp/$f; done
cp sizecalc.py sizecalc.py.bak1111 2>/dev/null || true
cp /tmp/sizecalc.py sizecalc.py; cp /tmp/autosize.py autosize.py
./venv/bin/python -m py_compile autosize.py sizecalc.py
sudo -n true && echo "sudo without password: OK" || echo "WARNING: sudo needs a password - the restart will fail and the sale would be switched off instead"
echo "--- what it would do now (nothing changed):"
./venv/bin/python autosize.py --show
( crontab -l 2>/dev/null | grep -v autosize.py; echo "22 23 * * * cd $HOME/deltabot && $HOME/deltabot/venv/bin/python autosize.py >> logs/autosize.log 2>&1" ) | crontab -
echo "cron: $(crontab -l | grep autosize.py)"
rm -f /tmp/autosize.py /tmp/sizecalc.py
