#!/bin/bash
# 15-Nov-2026: v5live_patch - (1) the live night seller can take the v5 rules from its config (default stays v4asl, so NOTHING changes
# for tonight); (2) new PAPER copy v5aslj = V5A-CG-SL + strike jump. All existing copies and all data collection keep running.
# Refuses while a live night position is open or between 22:30 and 01:00 IST. Restores the backups if the self-test fails.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s); run again after the night is closed"; exit 1; fi
for f in v5live_patch.py selftest_v5.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python v5live_patch.py
restore() { for f in nightlogic.py nightlive.py nightbot.py control.py ui.py night.sh; do [ -f $f.bak1115v5 ] && cp $f.bak1115v5 $f; done; echo "RESTORED the backups - nothing changed"; exit 1; }
./venv/bin/python -m py_compile nightlogic.py nightlive.py nightbot.py control.py ui.py || restore
./venv/bin/python selftest_v5.py || restore
sudo systemctl restart nightbot ui nightlive
sleep 6
echo "nightbot: $(systemctl is-active nightbot) | ui: $(systemctl is-active ui) | nightlive: $(systemctl is-active nightlive)"
./venv/bin/python nightlive.py --status | head -1
tail -n 3 logs/nightlive.log | cut -c1-200
echo "V5LIVE INSTALL DONE (live rules unchanged: still v4asl until --rule v5asl is set)"
