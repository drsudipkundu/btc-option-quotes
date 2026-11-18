#!/bin/bash
# 18-Nov-2026: new PAPER copy V5A-CG-SL-P (trend leg x1.5 when the premium is in the top 10 % of its last 365 days). No live orders;
# the live seller's code file (nightlive.py) is not touched and its rules are unchanged. Refuses 22:30-01:00 IST.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
for f in richpaper_patch.py selftest_richpaper.py prem_hist_seed.csv; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
FILES="nightlogic.py nightbot.py control.py ui.py"
for f in $FILES; do cp $f $f.bak1118p; done
restore() { for f in $FILES; do cp $f.bak1118p $f; done; echo "RESTORED the backups - nothing changed"; exit 1; }
./venv/bin/python richpaper_patch.py || restore
./venv/bin/python -m py_compile $FILES nightlive.py || restore
./venv/bin/python selftest_richpaper.py > logs/selftest_richpaper.txt 2>&1 || { tail -n 15 logs/selftest_richpaper.txt; restore; }
grep -h -E "^---|PASSED|trend leg" logs/selftest_richpaper.txt | cut -c1-170
[ -f state/prem_hist.csv ] || cp prem_hist_seed.csv state/prem_hist.csv
echo "premium history: $(wc -l < state/prem_hist.csv) nights"
sudo systemctl restart nightbot ui
sleep 6
echo "nightbot: $(systemctl is-active nightbot) | ui: $(systemctl is-active ui) | nightlive (not restarted): $(systemctl is-active nightlive)"
tail -n 2 logs/night.log | cut -c1-200
echo "RICH PAPER INSTALL DONE"
