#!/bin/bash
# 25-Nov-2026 c11: installs the option STRIKE-LIST logger (public data only; no keys, no orders; the night bot is not touched or restarted).
set -e
REF=${1:-main}
mkdir -p ~/deltabot/strikelog ~/deltabot/recorder
for f in strikelog.py selftest_strikelog.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o ~/deltabot/recorder/$f; done
cd ~/deltabot/recorder
python3 -m py_compile strikelog.py
python3 selftest_strikelog.py | tail -n 1
sudo tee /etc/systemd/system/strikelog.service >/dev/null <<UNIT
[Unit]
Description=Delta BTC option strike-list logger
After=network-online.target
[Service]
User=$USER
ExecStart=/usr/bin/python3 $HOME/deltabot/recorder/strikelog.py
Restart=always
RestartSec=15
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now strikelog
sleep 70
echo "strikelog: $(systemctl is-active strikelog)"
head -n 3 ~/deltabot/strikelog/strikelog_events.csv | cut -c1-220
tail -n 1 ~/deltabot/strikelog/strikelog_edge.csv | cut -c1-260
df -h / | tail -1
echo "STRIKELOG INSTALL DONE"
