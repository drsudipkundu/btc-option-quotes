#!/bin/bash
# Installs the order-book recorder as a systemd service that starts on boot and restarts if it stops.
# Public data only. Touches nothing of the trading bot (no .env, no keys, no orders).
set -e
mkdir -p ~/deltabot/obook ~/deltabot/recorder
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/main/server/obook_recorder.py -o ~/deltabot/recorder/obook_recorder.py
sudo tee /etc/systemd/system/obook-recorder.service >/dev/null <<UNIT
[Unit]
Description=Delta BTCUSD order-book recorder
After=network-online.target
[Service]
User=$USER
ExecStart=/usr/bin/python3 $HOME/deltabot/recorder/obook_recorder.py
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now obook-recorder
sleep 25
systemctl is-active obook-recorder
ls -la ~/deltabot/obook | tail -3
