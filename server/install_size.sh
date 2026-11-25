#!/bin/bash
# 25-Nov-2026 c15: Telegram /size x: ONE-night size multiplier (0.1 to 1, smaller only), back to normal by itself.
# Refuses 22:30-01:00 IST or with an open night position. Self-tests first; restores the backups on any failure. Telegram reads letterbox.py fresh each time (no restart needed for it).
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
for f in size_patch.py selftest_size.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
./venv/bin/python size_patch.py
restore() { for f in nightlive letterbox; do [ -f $f.py.bak1125s ] && cp $f.py.bak1125s $f.py; done; echo "RESTORED the backups - nothing changed"; exit 1; }
./venv/bin/python -m py_compile nightlive.py letterbox.py || restore
./venv/bin/python selftest_size.py > logs/selftest_size.txt 2>&1 || { tail -n 15 logs/selftest_size.txt; restore; }
for t in selftest_caution selftest_takeprofit selftest_juice selftest_letterbox selftest_retrylimit selftest_wingretry selftest_hedgeorder; do [ -f $t.py ] && { ./venv/bin/python $t.py > logs/$t.txt 2>&1 || { tail -n 12 logs/$t.txt; restore; }; }; done
grep -E "PASSED" logs/selftest_size.txt | cut -c1-150
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-230
echo "SIZE INSTALL DONE"
