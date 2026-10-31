#!/bin/bash
# 31-Oct-2026: ladder shadow fleet (v9/v10/v11/v12 parameter-health paper copies). Separate paper service "ladshadow";
# no other bot is touched. Adds the "Ladder health" tab (/lhealth) to the control page.
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/ladshadow.py -o ladshadow.py
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/ladshadow_ui_patch.py -o /tmp/ladshadow_ui_patch.py
python3 /tmp/ladshadow_ui_patch.py ~/deltabot
./venv/bin/python -m py_compile ladshadow.py ui.py
./venv/bin/python ladshadow.py --check | tail -n 4
cat > /tmp/ladshadow.service <<UNIT
[Unit]
Description=Ladder shadow fleet - v9/v10/v11/v12 parameter health (paper)
After=network-online.target
[Service]
User=$USER
WorkingDirectory=$HOME/deltabot
ExecStart=$HOME/deltabot/venv/bin/python $HOME/deltabot/ladshadow.py
Restart=always
RestartSec=15
[Install]
WantedBy=multi-user.target
UNIT
sudo cp /tmp/ladshadow.service /etc/systemd/system/ladshadow.service
sudo systemctl daemon-reload
sudo systemctl enable --now ladshadow
sudo systemctl restart ui
sleep 8
echo "ladshadow: $(systemctl is-active ladshadow)  ui: $(systemctl is-active ui)  nightlive: $(systemctl is-active nightlive)  variantbot: $(systemctl is-active variantbot)"
tail -n 2 logs/ladshadow.log
rm -f /tmp/ladshadow_ui_patch.py /tmp/ladshadow.service
