#!/bin/bash
# 25-Nov-2026 c10: hedge rule order (put AND call): target first, then 1 in, 1 out, 2 in, 2 out ... (in before out). Future last resort NOT included (27-Nov).
# Refuses 22:30-01:00 IST or with an open night position. Self-tests first; restores the backup on any failure.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
for f in hedgeorder_patch.py selftest_hedgeorder.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python hedgeorder_patch.py
restore() { [ -f nightlive.py.bak1125h ] && cp nightlive.py.bak1125h nightlive.py; echo "RESTORED the backup - nothing changed"; exit 1; }
./venv/bin/python -m py_compile nightlive.py || restore
./venv/bin/python selftest_hedgeorder.py > logs/selftest_hedgeorder.txt 2>&1 || { tail -n 15 logs/selftest_hedgeorder.txt; restore; }
for t in selftest_wingretry selftest_hedgerule; do [ -f $t.py ] && { ./venv/bin/python $t.py > logs/$t.txt 2>&1 || { tail -n 12 logs/$t.txt; restore; }; }; done
grep -E "^OK|PASSED" logs/selftest_hedgeorder.txt | cut -c1-150
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-230
echo "HEDGEORDER INSTALL DONE"
