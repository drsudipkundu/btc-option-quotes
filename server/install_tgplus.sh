#!/bin/bash
# 20-Nov-2026: Telegram commands /pnl /cum /tonight /guard /paper /server /ceiling (read only except /ceiling, which needs /ceiling yes).
# No trading service is restarted; the watchman picks the new commands up on its next run.
set -e
REF=${1:-main}
cd ~/deltabot
for f in tgplus.py tgplus_patch.py selftest_tgplus.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
cp letterbox.py letterbox.py.bak1120g2
restore() { cp letterbox.py.bak1120g2 letterbox.py; echo "RESTORED the backup - nothing changed"; exit 1; }
./venv/bin/python tgplus_patch.py || restore
./venv/bin/python -m py_compile letterbox.py tgplus.py || restore
./venv/bin/python selftest_tgplus.py > logs/selftest_tgplus.txt 2>&1 || { tail -n 15 logs/selftest_tgplus.txt; restore; }
grep -h -E "^---|PASSED" logs/selftest_tgplus.txt
./venv/bin/python -c "import letterbox; print(letterbox.set_menu())"
echo "live check:"; ./venv/bin/python -c "import tgplus; print(tgplus.tonight_text()); print(tgplus.cum_text())" 2>&1 | tail -n 12
echo "TELEGRAM PLUS INSTALL DONE"
