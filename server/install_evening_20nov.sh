#!/bin/bash
# 20-Nov-2026 evening install (one /install yes):
#  1) paper plus: paper copies K / G15 / HK, live recorders (postfill prices, hedge availability), guard mode in insurance rows
#  2) top-up: sale at the small base; once every far option is bought within 1 hour (and BTC not too close, price >= 80 %),
#     extra up to the big base; autosize writes base (small) and base_big (big); limits follow base_big.
# Refuses 22:30-01:00 IST and while the live seller has an open leg. Restarts nightbot, ui, nightlive.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
grep -q "gk_unhedged" nightlogic.py || { echo "REFUSED: guard rule not installed"; exit 1; }
for f in paperplus_patch.py topup_patch.py selftest_paperplus.py selftest_recorders.py selftest_topup.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
FILES="nightlogic.py nightlive.py nightbot.py control.py ui.py autosize.py sizecalc.py"
for f in $FILES; do cp $f $f.bak1120e; done
restore() { for f in $FILES; do cp $f.bak1120e $f; done; echo "RESTORED the backups - nothing changed"; exit 1; }
./venv/bin/python paperplus_patch.py || restore
./venv/bin/python topup_patch.py || restore
./venv/bin/python -m py_compile $FILES || restore
for t in selftest_topup selftest_paperplus selftest_recorders selftest_guardrule selftest_hedgerule selftest_flagpaper selftest_wingretry; do
  ./venv/bin/python $t.py > logs/$t.e.txt 2>&1 || { tail -n 15 logs/$t.e.txt; restore; }
done
grep -h -E "^---|PASSED" logs/selftest_topup.e.txt logs/selftest_paperplus.e.txt logs/selftest_recorders.e.txt | cut -c1-170
echo "what tonight's 23:22 run would do now:"
./venv/bin/python autosize.py --show 2>&1 | tail -n 2 | cut -c1-250
sudo systemctl restart nightbot ui nightlive
sleep 8
echo "nightbot: $(systemctl is-active nightbot) | ui: $(systemctl is-active ui) | nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-200
echo "EVENING INSTALL DONE"
