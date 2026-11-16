#!/bin/bash
# 16-Nov-2026: letterbox (settings without the PC, fixed list only, never an order) + extra Telegram commands. No bot is restarted.
set -e
REF=${1:-main}
cd ~/deltabot
for f in letterbox.py letterbox_patch.py selftest_letterbox.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python letterbox_patch.py
restore() { [ -f nightwatch.py.bak1116lb ] && cp nightwatch.py.bak1116lb nightwatch.py; echo "RESTORED nightwatch.py - letterbox not scheduled"; exit 1; }
./venv/bin/python -m py_compile nightwatch.py letterbox.py || restore
./venv/bin/python selftest_letterbox.py | tail -n 2 | grep -q "SELFTEST LETTERBOX PASSED" || restore
echo "SELFTEST LETTERBOX PASSED"
( crontab -l 2>/dev/null | grep -v "letterbox.py" ; echo "*/2 * * * * cd /home/ubuntu/deltabot && /home/ubuntu/deltabot/venv/bin/python letterbox.py >> logs/letterbox.log 2>&1" ) | crontab -
./venv/bin/python letterbox.py; cat state/letterbox.json; echo
crontab -l | grep -c letterbox
./venv/bin/python nightwatch.py >/dev/null 2>&1 && echo "nightwatch runs OK"
echo "LETTERBOX INSTALL DONE"
