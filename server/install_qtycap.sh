#!/bin/bash
# 26-Nov-2026 c26 (Sudip 19:45): per-night quantity totals (sold / bought) tied to the base, on top of the existing guard limits
# (max per order, max open - already follow the base via autosize). Closing orders are never blocked.
# Refuses 22:30-01:00 IST or with an open night position. Self-tests first; restores the backup on any failure.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
for f in qtycap_patch.py selftest_qtycap.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
restore() { [ -f nightlive.py.bak1126q ] && cp nightlive.py.bak1126q nightlive.py; echo "RESTORED the backup - nothing changed"; exit 1; }
./venv/bin/python qtycap_patch.py || restore
./venv/bin/python -m py_compile nightlive.py || restore
./venv/bin/python selftest_qtycap.py > logs/selftest_qtycap.txt 2>&1 || { tail -n 15 logs/selftest_qtycap.txt; restore; }
for t in selftest_guardrule selftest_hedgerule selftest_wingretry selftest_flagpaper; do [ -f $t.py ] && { ./venv/bin/python $t.py > logs/$t.q.txt 2>&1 || { tail -n 12 logs/$t.q.txt; restore; }; }; done
grep -E "^OK|PASSED" logs/selftest_qtycap.txt | cut -c1-120
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-200
echo "QTYCAP INSTALL DONE: night caps sold/bought = 7 x base (edit state/limits.json: max_sold_night_btc, max_bought_night_btc)"
