#!/bin/bash
# 29-Oct-2026: shadow fleet (parameter-health monitor) for the night sell. Separate paper service "shadowbot";
# the real night bot is not touched. Adds the "Parameter health" tab to the control page.
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/shadow.py -o shadow.py
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/shadow_ui_patch.py -o /tmp/shadow_ui_patch.py
python3 /tmp/shadow_ui_patch.py ~/deltabot
./venv/bin/python -m py_compile shadow.py ui.py
sed -e 's/Delta night option-sell bot (paper mode)/Shadow fleet - night sell parameter health (paper)/' -e 's#nightbot.py#shadow.py#' nightbot.service > shadowbot.service
sudo cp shadowbot.service /etc/systemd/system/shadowbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now shadowbot
sudo systemctl restart ui
./venv/bin/python shadow.py --check
sleep 3
echo "shadowbot: $(systemctl is-active shadowbot)  ui: $(systemctl is-active ui)"
tail -n 2 logs/shadow.log
rm -f /tmp/shadow_ui_patch.py
