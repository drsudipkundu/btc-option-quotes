#!/bin/bash
# 18-Nov-2026: LIVE size flags for the night seller (nightlive.py). Mode is read from server/livefl_mode.txt in the repo: off | f | h
#   off = live sells exactly as before; f = any flag -> trend leg and boost x1.5; h = same and x0.5 when no flag.
# Also sets guard limits to 5 x base per order / 12 x base open when the mode is f or h (3 x / 8 x when off).
# Refuses 22:30-01:00 IST and refuses while the live seller has an open leg. Needs install_flagpaper.sh done first.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
grep -q "_rich_qty" nightlogic.py || { echo "REFUSED: flag paper patch not installed"; exit 1; }
for f in livefl_patch.py selftest_livefl.py livefl_mode.txt; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
MODE=$(tr -d ' \n\r' < livefl_mode.txt | tr A-Z a-z)
case "$MODE" in off|f|h) ;; *) echo "REFUSED: mode '$MODE' is not off, f or h"; exit 1;; esac
FILES="nightlive.py nightlogic.py autosize.py"
for f in $FILES; do cp $f $f.bak1118l; done
cp state/night_live_cfg.json state/night_live_cfg.json.bak1118l 2>/dev/null || true
cp state/limits.json state/limits.json.bak1118l 2>/dev/null || true
restore() { for f in $FILES; do cp $f.bak1118l $f; done; cp state/night_live_cfg.json.bak1118l state/night_live_cfg.json 2>/dev/null || true; cp state/limits.json.bak1118l state/limits.json 2>/dev/null || true; echo "RESTORED the backups - nothing changed"; exit 1; }
./venv/bin/python livefl_patch.py || restore
./venv/bin/python -m py_compile $FILES || restore
./venv/bin/python selftest_livefl.py > logs/selftest_livefl.txt 2>&1 || { tail -n 15 logs/selftest_livefl.txt; restore; }
./venv/bin/python selftest_flagpaper.py > logs/selftest_flagpaper2.txt 2>&1 || { tail -n 15 logs/selftest_flagpaper2.txt; restore; }
grep -h -E "^---|PASSED" logs/selftest_livefl.txt | cut -c1-170
./venv/bin/python - <<PY
import json, os, sys
sys.path.insert(0, os.getcwd())
import nightlive as LV, autosize as AS
LV.put_cfg(flagmode="$MODE")
print("flagmode now:", LV.cfg().get("flagmode"))
print(AS.sync_limits(float(LV.cfg().get("base", 0.02))) or "size limits unchanged")
PY
sudo systemctl restart nightlive
sleep 6
echo "nightlive: $(systemctl is-active nightlive)"
tail -n 1 logs/nightlive.log | cut -c1-200
echo "LIVE FLAGS INSTALL DONE, mode $MODE"
