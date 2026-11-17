#!/bin/bash
# 17-Nov-2026: juice_patch - the live night seller closes the night when at most 10 % of the night's premium is left to earn
# (Sudip 17-Nov 09:40). Refuses 22:30-01:00 IST or with an open night position. Sets the rule to 10 %.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
for f in juice_patch.py selftest_juice.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python juice_patch.py
restore() { [ -f nightlive.py.bak1117j ] && cp nightlive.py.bak1117j nightlive.py; echo "RESTORED the backup - nothing changed"; exit 1; }
./venv/bin/python -m py_compile nightlive.py || restore
./venv/bin/python selftest_juice.py > logs/selftest_juice.txt 2>&1 || { tail -n 15 logs/selftest_juice.txt; restore; }
grep -E "^---|=>|PASSED" logs/selftest_juice.txt | cut -c1-150
./venv/bin/python nightlive.py --juice 10 | cut -c1-200
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-230
echo "JUICE INSTALL DONE"
