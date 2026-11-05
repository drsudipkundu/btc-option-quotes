#!/bin/bash
# 5-Nov-2026: Skip-night weekly sell (PAPER) as its own service "skipweekly" + guard false-alarm fix in nightbot.
set -e
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 0100 ]; then echo "Not between 22:30 and 01:00 IST - please run after 01:00."; exit 1; fi
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/skipweekly.py -o skipweekly.py
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/guardfix_patch.py -o /tmp/guardfix_patch.py
python3 /tmp/guardfix_patch.py ~/deltabot
./venv/bin/python -m py_compile skipweekly.py nightbot.py
sed -e 's/Delta night option-sell bot (paper mode)/Skip-night weekly 10% sell (paper)/' -e 's#nightbot.py#skipweekly.py#' nightbot.service > skipweekly.service
sudo cp skipweekly.service /etc/systemd/system/skipweekly.service
sudo systemctl daemon-reload
sudo systemctl enable --now skipweekly
sudo systemctl restart nightbot
./venv/bin/python skipweekly.py --check
sleep 3
echo "skipweekly: $(systemctl is-active skipweekly)  nightbot: $(systemctl is-active nightbot)"
grep -c "def live_expected" nightbot.py
tail -n 2 logs/skipweekly.log
rm -f /tmp/guardfix_patch.py
echo SKIPWEEKLY INSTALL DONE
