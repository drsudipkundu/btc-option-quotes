#!/bin/bash
# 16-Nov-2026: wing2_patch - smart buy for the hedge, far option sold after the sold option is closed (if anybody bids),
# automatic base with a ceiling (off until `autosize.py --ceiling 0.12 2026-11-17`). Refuses 22:30-01:00 IST or with an open night position.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
for f in wing2_patch.py selftest_wing.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python wing2_patch.py
restore() { for f in nightlive.py autosize.py; do [ -f $f.bak1116w2 ] && cp $f.bak1116w2 $f; done; echo "RESTORED the backups - nothing changed"; exit 1; }
./venv/bin/python -m py_compile nightlive.py autosize.py || restore
./venv/bin/python selftest_wing.py > logs/selftest_wing.txt 2>&1 || { tail -n 15 logs/selftest_wing.txt; restore; }
grep -E "^---|=>|PASSED" logs/selftest_wing.txt | cut -c1-150
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-230
echo "WING2 INSTALL DONE"
