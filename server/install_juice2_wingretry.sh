#!/bin/bash
# 18-Nov-2026: one approval for (1) juice2 - 5 % rule on net credit incl. far options' resale value, (2) wing retry - missing far
# options tried again every 5 min (Sudip 17-Nov 22:35 and 23:37). Refuses 22:30-01:00 IST or with an open night position.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
for f in juice2_patch.py wingretry_patch.py selftest_juice.py selftest_wingretry.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
cp nightlive.py nightlive.py.bak1118both
restore() { cp nightlive.py.bak1118both nightlive.py; echo "RESTORED the backup - nothing changed"; exit 1; }
./venv/bin/python juice2_patch.py || restore
./venv/bin/python wingretry_patch.py || restore
./venv/bin/python -m py_compile nightlive.py || restore
./venv/bin/python selftest_juice.py > logs/selftest_juice2.txt 2>&1 || { tail -n 15 logs/selftest_juice2.txt; restore; }
./venv/bin/python selftest_wingretry.py > logs/selftest_wingretry.txt 2>&1 || { tail -n 15 logs/selftest_wingretry.txt; restore; }
grep -h -E "^---|PASSED" logs/selftest_juice2.txt logs/selftest_wingretry.txt | cut -c1-170
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-200
echo "JUICE2 + WING RETRY INSTALL DONE"
