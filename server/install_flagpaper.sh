#!/bin/bash
# 18-Nov-2026: two more PAPER copies: V5A-CG-SL-F (any flag -> trend leg x1.5) and V5A-CG-SL-H (the same, and x0.5 with no flag).
# No live orders; nightlive.py is not touched and the live rules are unchanged. Refuses 22:30-01:00 IST.
set -e
REF=${1:-main}
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
for f in flagpaper_patch.py selftest_flagpaper.py selftest_richpaper.py iv_hist_seed.csv; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
FILES="nightlogic.py nightbot.py control.py ui.py"
for f in $FILES; do cp $f $f.bak1118f; done
restore() { for f in $FILES; do cp $f.bak1118f $f; done; echo "RESTORED the backups - nothing changed"; exit 1; }
./venv/bin/python flagpaper_patch.py || restore
./venv/bin/python -m py_compile $FILES nightlive.py || restore
./venv/bin/python selftest_flagpaper.py > logs/selftest_flagpaper.txt 2>&1 || { tail -n 15 logs/selftest_flagpaper.txt; restore; }
./venv/bin/python selftest_richpaper.py > logs/selftest_richpaper.txt 2>&1 || { tail -n 15 logs/selftest_richpaper.txt; restore; }
grep -h -E "^---|PASSED" logs/selftest_flagpaper.txt logs/selftest_richpaper.txt | cut -c1-150
[ -f state/iv_hist.csv ] || cp iv_hist_seed.csv state/iv_hist.csv
echo "history: premium $(wc -l < state/prem_hist.csv) nights, volatility $(wc -l < state/iv_hist.csv) nights"
./venv/bin/python - <<'PY' || echo "LIVE LOOK FAILED (the copies then treat the 4h RSI flag as off)"
import time, statistics, nightbot as NB
f = NB.Feed(); now = time.time(); print("live look: 4h RSI now %.1f" % f.rsi4h(now))
import datetime as dt
ch = [o for o in NB.parse_chain(f.d.public("/v2/tickers", {"contract_types": "call_options,put_options", "underlying_asset_symbols": "BTC"})["result"]) if o["exp"] > now and o["iv"] > 0]
e = min(o["exp"] for o in ch); iv = [o["iv"] for o in ch if o["exp"] == e]
print("live look: nearest expiry %s, %d options, implied volatility median %.3f (min %.3f, max %.3f)" % (dt.datetime.utcfromtimestamp(e).strftime("%d-%b"), len(iv), statistics.median(iv), min(iv), max(iv)))
PY
sudo systemctl restart nightbot ui
sleep 6
echo "nightbot: $(systemctl is-active nightbot) | ui: $(systemctl is-active ui) | nightlive (not restarted): $(systemctl is-active nightlive)"
tail -n 2 logs/night.log | cut -c1-200
echo "FLAG PAPER INSTALL DONE"
