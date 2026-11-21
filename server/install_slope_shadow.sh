#!/bin/bash
# Installs the SMA100-slope SHADOW recorder (v15 extra-call size study) as a systemd service.
# Public data only: no .env, no keys, no orders.  Does NOT patch or restart any trading bot (variantbot / nightlive / ladderlive / ui untouched).
# It only READS ~/deltabot/logs/calls_lv15.csv when you ask for a report.   Usage: bash install_slope_shadow.sh [commit]
set -eo pipefail
REF="${1:-main}"
mkdir -p ~/deltabot/recorder ~/deltabot/slope_shadow
curl -fsSL "https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/slope_shadow.py" -o ~/deltabot/recorder/slope_shadow.py.new
python3 -m py_compile ~/deltabot/recorder/slope_shadow.py.new
mv ~/deltabot/recorder/slope_shadow.py.new ~/deltabot/recorder/slope_shadow.py
# self-test without writing anything: today's row from Delta's public candles
python3 ~/deltabot/recorder/slope_shadow.py once | head -12
sudo tee /etc/systemd/system/slope-shadow.service >/dev/null <<UNIT
[Unit]
Description=SMA100 slope shadow recorder (v15 extra-call study)
After=network-online.target
[Service]
User=$USER
ExecStart=/usr/bin/python3 $HOME/deltabot/recorder/slope_shadow.py run
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now slope-shadow
sleep 8
systemctl is-active slope-shadow
ls -la ~/deltabot/slope_shadow
echo "report any time:  python3 ~/deltabot/recorder/slope_shadow.py report"
