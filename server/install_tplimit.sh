#!/bin/bash
# 3-Nov-2026: 90% buy-back as a RESTING LIMIT ORDER at 10% of the sale price, in every night-sell version:
# live seller (nightlive), paper copies (nightbot via nightlogic), both shadow fleets (shadow.py, own decay level).
# Run OUTSIDE 22:30-01:00 IST. Restarts nightlive, nightbot, shadowbot, ui. An open live leg gets its resting order
# placed within a minute of the restart. Usage: bash install_tplimit.sh <commit>
set -e
C=${1:?commit}
H=~/deltabot
R=https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$C/server
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -le 100 ]; then echo "STOP: night window 22:30-01:00 IST"; exit 1; fi
cd $H
for f in nightlive.py shadow.py stratinfo.py tplimit_patch.py; do cp -a $f $f.bak_pre_tp 2>/dev/null || true; curl -fsSL $R/$f -o $f.new; mv $f.new $f; done
venv/bin/python tplimit_patch.py $H
venv/bin/python -m py_compile nightlogic.py nightlive.py shadow.py stratinfo.py nightbot.py
sudo systemctl restart nightlive nightbot shadowbot ui
sleep 6
systemctl is-active nightlive nightbot shadowbot ui
venv/bin/python nightlive.py --status | head -c 600; echo
tail -n 3 logs/nightlive.log
echo TPLIMIT INSTALL DONE
