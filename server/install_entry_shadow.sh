#!/bin/bash
# Installs the ENTRY-TIME shadow recorder ("paperboy"): public Delta data only, no keys, no orders. Touches no bot. Safe at any hour.
set -eo pipefail
REF="${1:-main}"
mkdir -p ~/deltabot/recorder ~/deltabot/entry_shadow
curl -fsSL "https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/entry_shadow.py" -o ~/deltabot/recorder/entry_shadow.py.new
python3 -m py_compile ~/deltabot/recorder/entry_shadow.py.new
mv ~/deltabot/recorder/entry_shadow.py.new ~/deltabot/recorder/entry_shadow.py
python3 ~/deltabot/recorder/entry_shadow.py once | cut -c1-300
sudo tee /etc/systemd/system/entry-shadow.service >/dev/null <<UNIT
[Unit]
Description=Entry-time shadow recorder (paper entries every 30 min)
After=network-online.target
[Service]
User=$USER
ExecStart=/usr/bin/python3 $HOME/deltabot/recorder/entry_shadow.py run
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now entry-shadow
sleep 70
echo "entry-shadow: $(systemctl is-active entry-shadow)"
ls -la ~/deltabot/entry_shadow; { tail -2 ~/deltabot/entry_shadow/entries.csv 2>/dev/null | cut -c1-200; } || true
echo "ENTRY SHADOW INSTALL DONE   report any time: python3 ~/deltabot/recorder/entry_shadow.py report"
