#!/bin/bash
# 20-Nov-2026: PAPER safety net (netpaper.py, read only, places NO order) as service "netpaper",
# plus the side recorder + wider Drive copy (install_sidewatch.sh, safe to run again). Trading is not restarted.
set -e
REF=${1:-main}
cd ~/deltabot
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/install_sidewatch.sh -o install_sidewatch.sh
bash install_sidewatch.sh $REF
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/netpaper.py -o netpaper.py.new
./venv/bin/python -m py_compile netpaper.py.new
mv netpaper.py.new netpaper.py
./venv/bin/python netpaper.py --once | tail -2
sudo tee /etc/systemd/system/netpaper.service >/dev/null <<UNIT
[Unit]
Description=Night-sell PAPER safety net (read only, no orders)
After=network-online.target
[Service]
User=$USER
WorkingDirectory=$HOME/deltabot
ExecStart=$HOME/deltabot/venv/bin/python $HOME/deltabot/netpaper.py
Restart=always
RestartSec=20
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now netpaper
sudo systemctl restart netpaper
sleep 5
echo "netpaper: $(systemctl is-active netpaper)   nightlive: $(systemctl is-active nightlive)"
echo "NETPAPER INSTALL DONE"
