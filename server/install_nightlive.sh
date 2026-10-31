#!/bin/bash
# 31-Oct-2026: LIVE night seller service "nightlive" (starts DISARMED, paper client). Paper bots untouched.
set -e
cd ~/deltabot
REF=${1:-main}
for f in nightlive.py nightlive_patch.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o /tmp/$f; done
cp /tmp/nightlive.py nightlive.py
python3 /tmp/nightlive_patch.py ~/deltabot
./venv/bin/python -m py_compile nightlive.py ui.py control.py
[ -f state/night_live_cfg.json ] || ./venv/bin/python nightlive.py --client paper
./venv/bin/python nightlive.py --disarm
sed -e 's/Delta night option-sell bot (paper mode)/Delta night option-sell LIVE (nightlive)/' -e 's#nightbot.py#nightlive.py#' nightbot.service > nightlive.service
sudo cp nightlive.service /etc/systemd/system/nightlive.service
sudo systemctl daemon-reload
sudo systemctl enable --now nightlive
sudo systemctl restart ui
sleep 4
echo "nightlive: $(systemctl is-active nightlive)  ui: $(systemctl is-active ui)"
./venv/bin/python nightlive.py --status | head -c 600; echo
cat state/limits.json 2>/dev/null || echo "limits: defaults (0.05 per order, 0.15 open, 60 USD/day)"
tail -n 3 logs/nightlive.log
rm -f /tmp/nightlive.py /tmp/nightlive_patch.py
