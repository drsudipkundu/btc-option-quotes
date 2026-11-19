#!/bin/bash
# 20-Nov-2026 (Sudip 19-Nov 21:55: every variable on paper, record all data): paper copies V5A-CG-SL-K (guard at strike),
# -G15 (guard 1.5 x ATR), -HK (flags H + hedge-exists + guard at strike); live recorders postfill_prices.csv, hedge_exists.csv;
# guard insurance rows name the mode. Live trading rules unchanged.
# Refuses 22:30-01:00 IST and while the live seller has an open leg (it restarts nightlive).
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
grep -q "gk_unhedged" nightlogic.py || { echo "REFUSED: guard rule not installed"; exit 1; }
for f in paperplus_patch.py selftest_paperplus.py selftest_recorders.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
FILES="nightlogic.py nightlive.py nightbot.py control.py ui.py"
for f in $FILES; do cp $f $f.bak1120p2; done
restore() { for f in $FILES; do cp $f.bak1120p2 $f; done; echo "RESTORED the backups - nothing changed"; exit 1; }
./venv/bin/python paperplus_patch.py || restore
./venv/bin/python -m py_compile $FILES || restore
for t in selftest_paperplus selftest_recorders selftest_guardrule selftest_hedgerule selftest_flagpaper selftest_wingretry; do
  ./venv/bin/python $t.py > logs/$t.p.txt 2>&1 || { tail -n 15 logs/$t.p.txt; restore; }
done
grep -h -E "^---|PASSED" logs/selftest_paperplus.p.txt logs/selftest_recorders.p.txt | cut -c1-170
sudo systemctl restart nightbot ui nightlive
sleep 8
echo "nightbot: $(systemctl is-active nightbot) | ui: $(systemctl is-active ui) | nightlive: $(systemctl is-active nightlive)"
tail -n 2 logs/night.log | cut -c1-220
echo "PAPER PLUS INSTALL DONE"
