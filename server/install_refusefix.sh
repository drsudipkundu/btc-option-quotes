#!/bin/bash
# 24-Nov-2026 c03: a strike Delta refuses (HTTP 400, e.g. open-interest cap) = a failed try, then the bot moves to the next strike.
# Refuses 22:30-01:00 IST or with an open night position. Self-tests first; restores the backup on any failure.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
for f in refusefix_patch.py selftest_refusefix.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python refusefix_patch.py
restore() { [ -f nightlive.py.bak1124r ] && cp nightlive.py.bak1124r nightlive.py; echo "RESTORED the backup - nothing changed"; exit 1; }
./venv/bin/python -m py_compile nightlive.py || restore
./venv/bin/python selftest_refusefix.py > logs/selftest_refusefix.txt 2>&1 || { tail -n 15 logs/selftest_refusefix.txt; restore; }
grep -E "^OK|PASSED" logs/selftest_refusefix.txt | cut -c1-150
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-230
echo "REFUSEFIX INSTALL DONE"
