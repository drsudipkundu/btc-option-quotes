#!/bin/bash
# 19-Nov-2026 (Sudip 14:17, 16:42): live crash guard per side + far put price ceiling 30 %; - fully hedged side: far option protects (guard 2 x ATR as before);
# side not fully hedged: guard fires when BTC touches the sold strike; capital formula takes the safer of hedged / unhedged.
# Refuses 22:30-01:00 IST and while the live seller has an open leg. Needs install_livefl.sh (hedge rule) first.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
grep -q "hedge_ok" nightlive.py || { echo "REFUSED: hedge rule (install_livefl.sh) not installed"; exit 1; }
for f in guardrule_patch.py selftest_guardrule.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
FILES="nightlive.py nightlogic.py sizecalc.py"
for f in $FILES; do cp $f $f.bak1119g2; done
restore() { for f in $FILES; do cp $f.bak1119g2 $f; done; echo "RESTORED the backups - nothing changed"; exit 1; }
./venv/bin/python guardrule_patch.py || restore
./venv/bin/python -m py_compile $FILES || restore
for t in selftest_guardrule selftest_hedgerule selftest_wingretry selftest_flagpaper; do
  ./venv/bin/python $t.py > logs/$t.g.txt 2>&1 || { tail -n 15 logs/$t.g.txt; restore; }
done
grep -h -E "^---|PASSED" logs/selftest_guardrule.g.txt logs/selftest_hedgerule.g.txt | cut -c1-170
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-200
echo "GUARD RULE INSTALL DONE"
