#!/bin/bash
# 1-Nov-2026: (1) CE leg with Smart Sell for the PAPER ladders (bot.py v9, variants.py v10/v11/v12);
# (2) the LIVE ladder runner "ladderlive" installed as a service with EVERY ladder DISARMED (it places no order until
# a ladder is armed with Sudip's yes). Restarts deltabot, variantbot, ui. Usage: bash install_ladcall.sh <commit>
set -e
C=${1:?commit}
H=~/deltabot
R=https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$C/server
cd $H
for f in ssjob.py ladcall.py ladderlive.py ladcall_patch.py stratinfo.py; do curl -fsSL $R/$f -o $f.new; mv $f.new $f; done
venv/bin/python ladcall_patch.py $H
venv/bin/python -m py_compile ssjob.py ladcall.py ladderlive.py stratinfo.py bot.py variants.py
[ -f state/ladder_live_cfg.json ] || venv/bin/python -c "import ladderlive as L; L.save_cfg(L.load_cfg())"
sed -e 's/Description=.*/Description=LIVE ladder runner (all ladders disarmed until armed)/' -e 's#nightbot.py#ladderlive.py#' nightbot.service > ladderlive.service
grep -q ladderlive.py ladderlive.service
sudo cp ladderlive.service /etc/systemd/system/ladderlive.service
sudo systemctl daemon-reload
sudo systemctl enable --now ladderlive
sudo systemctl restart deltabot variantbot ui
sleep 6
systemctl is-active deltabot variantbot ui ladderlive nightbot nightlive
venv/bin/python ladderlive.py --status
tail -n 2 logs/ladderlive.log
grep -i "call leg" logs/bot.log logs/variants.log | tail -n 3 || true
echo LADCALL INSTALL DONE
