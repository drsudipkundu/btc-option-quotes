#!/bin/bash
# 1-Nov-2026: Smart Sell for the paper night copies (nightbot) and both shadow fleets. Paper only.
# Restarts nightbot, shadowbot and ui (refuses 22:30-01:00 IST). The live night seller (nightlive) is not touched.
set -e
C=${1:?commit}
H=~/deltabot
R=https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$C/server
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -le 100 ]; then echo "STOP: night window 22:30-01:00 IST"; exit 1; fi
cd $H
for f in smartsell.py shadow.py stratinfo.py smartsell_patch.py; do curl -fsSL $R/$f -o $f.new; mv $f.new $f; done
venv/bin/python smartsell_patch.py $H
venv/bin/python -m py_compile smartsell.py shadow.py stratinfo.py nightbot.py
sudo systemctl restart nightbot shadowbot ui
sleep 5
systemctl is-active nightbot shadowbot ui nightlive
tail -n 2 logs/night.log 2>/dev/null || true
tail -n 1 logs/shadow.log
echo SMARTSELL INSTALL DONE
