#!/bin/bash
# 18-Nov-2026: juice2_patch - little-premium-left exit measured on NET credit (premium sold - hedges paid) and counting the
# far options' resale value (Sudip 17-Nov 22:35). Refuses 22:30-01:00 IST or with an open night position.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
for f in juice2_patch.py selftest_juice.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python juice2_patch.py
restore() { [ -f nightlive.py.bak1118j2 ] && cp nightlive.py.bak1118j2 nightlive.py; echo "RESTORED the backup - nothing changed"; exit 1; }
./venv/bin/python -m py_compile nightlive.py || restore
./venv/bin/python selftest_juice.py > logs/selftest_juice2.txt 2>&1 || { tail -n 15 logs/selftest_juice2.txt; restore; }
grep -E "PASSED" logs/selftest_juice2.txt
grep -o "'juice': [0-9.]*" state/night_live_cfg.json || ./venv/bin/python -c "import json;print('juice', json.load(open('state/night_live_cfg.json')).get('juice'))"
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
echo "JUICE2 INSTALL DONE"
