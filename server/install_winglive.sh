#!/bin/bash
# 16-Nov-2026: wing_live_patch - always-on hedge for the LIVE night seller behind one setting (off until `nightlive.py --wing 4`).
# Refuses while a live night position is open or between 22:30 and 01:00 IST. Restores the backups if the self-test fails.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s); run again after the night is closed"; exit 1; fi
for f in wing_live_patch.py selftest_wing.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python wing_live_patch.py
restore() { for f in nightlive.py nightbot.py; do [ -f $f.bak1116w ] && cp $f.bak1116w $f; done; echo "RESTORED the backups - nothing changed"; exit 1; }
./venv/bin/python -m py_compile nightlive.py nightbot.py || restore
./venv/bin/python selftest_wing.py > logs/selftest_wing.txt 2>&1 || { tail -n 15 logs/selftest_wing.txt; restore; }
grep -E "^---|=> crash|PASSED" logs/selftest_wing.txt | cut -c1-150
sudo systemctl restart nightbot nightlive
sleep 6
echo "nightbot: $(systemctl is-active nightbot) | nightlive: $(systemctl is-active nightlive)"
tail -n 2 logs/nightlive.log | cut -c1-230
echo "WING INSTALL DONE (hedge is OFF until: ./venv/bin/python nightlive.py --wing 4)"
