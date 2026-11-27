#!/bin/bash
# 27-Nov-2026 c31 (Sudip 15:29 "both yes"): top-up window until 02:30 IST (was 1 hour) + per-night quantity cap follows the BIG base.
# Changes the live seller (nightlive.py) and restarts it. Refuses 22:30-01:00 IST or with an open night position. Self-tests first; restores the backup on any failure.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
for f in topup0230_patch.py selftest_topup0230.py selftest_topupside.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
restore() { [ -f nightlive.py.bak1127t ] && cp nightlive.py.bak1127t nightlive.py; echo "RESTORED the backup - nothing changed"; exit 1; }
./venv/bin/python topup0230_patch.py || restore
./venv/bin/python -m py_compile nightlive.py || restore
./venv/bin/python selftest_topup0230.py > logs/selftest_topup0230.txt 2>&1 || { tail -n 15 logs/selftest_topup0230.txt; restore; }
for t in selftest_topupside selftest_qtycap selftest_cut selftest_guardrule selftest_hedgerule selftest_wingretry; do [ -f $t.py ] && { ./venv/bin/python $t.py > logs/$t.t.txt 2>&1 || { echo "regression $t failed:"; tail -n 12 logs/$t.t.txt; restore; }; }; done
grep -E "^OK|PASSED" logs/selftest_topup0230.txt | cut -c1-130
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-200
echo "--- sizes now (read only):"
./venv/bin/python -c "import json;c=json.load(open('state/night_live_cfg.json'));l=json.load(open('state/limits.json'));a=json.load(open('state/autosize.json'));print('base',c.get('base'),'base_big',c.get('base_big'),'| ceiling',a.get('ceiling'),'| limits',{k:l[k] for k in l if 'btc' in k})"
echo "TOPUP0230 INSTALL DONE"
