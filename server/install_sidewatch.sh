#!/bin/bash
# 20-Nov-2026: sidewatch (read-only per-side night recorder for the parked put/call sizing + capital-per-side ideas)
# and a wider daily Drive copy (live night logs + finished option-book hours). No bot is restarted, no trading change.
set -e
REF=${1:-main}
cd ~/deltabot
cp drivesync.sh drivesync.sh.bak1120 2>/dev/null || true
for f in sidewatch.py drivesync.sh; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f.new; done
./venv/bin/python -m py_compile sidewatch.py.new
bash -n drivesync.sh.new
mv sidewatch.py.new sidewatch.py; mv drivesync.sh.new drivesync.sh; chmod +x drivesync.sh
./venv/bin/python sidewatch.py --dry | tail -3
L="45 17 * * * cd $HOME/deltabot && venv/bin/python sidewatch.py >> logs/sidewatch.log 2>&1"
( crontab -l 2>/dev/null | grep -v sidewatch.py ; echo "$L" ) | crontab -
if command -v rclone >/dev/null && rclone listremotes 2>/dev/null | grep -q '^gdrive:'; then
  crontab -l | grep -q drivesync.sh || ( crontab -l 2>/dev/null ; echo "5 18 * * * bash $HOME/deltabot/drivesync.sh" ) | crontab -
  echo "drive remote: OK"
else
  echo "drive remote gdrive: NOT configured - Drive copy stays with the e-mail backup"
fi
crontab -l | grep -E "sidewatch|drivesync"
./venv/bin/python sidewatch.py | tail -2
echo "SIDEWATCH INSTALL DONE"
