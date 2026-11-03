#!/bin/bash
# 3-Nov-2026: funding logger (read-only). New service "fundlog": hourly BTCUSD funding rate + real funding transactions per
# account -> logs/funding_*.csv, page /funding on the control page. Only "ui" is restarted; no trading bot is touched.
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/fundlog.py -o fundlog.py
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/fundlog_ui_patch.py -o /tmp/fundlog_ui_patch.py
python3 /tmp/fundlog_ui_patch.py ~/deltabot
./venv/bin/python -m py_compile fundlog.py ui.py
echo "--- first pass (read-only):"
./venv/bin/python fundlog.py --once | tail -n 40
cat > /tmp/fundlog.service <<UNIT
[Unit]
Description=Funding logger - BTCUSD funding rate and real funding per account (read-only)
After=network-online.target
[Service]
User=$USER
WorkingDirectory=$HOME/deltabot
ExecStart=$HOME/deltabot/venv/bin/python $HOME/deltabot/fundlog.py
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
UNIT
sudo cp /tmp/fundlog.service /etc/systemd/system/fundlog.service
sudo systemctl daemon-reload
sudo systemctl enable --now fundlog
sudo systemctl restart ui
sleep 5
echo "fundlog: $(systemctl is-active fundlog)  ui: $(systemctl is-active ui)  nightlive: $(systemctl is-active nightlive)  deltabot: $(systemctl is-active deltabot)  variantbot: $(systemctl is-active variantbot)  ladshadow: $(systemctl is-active ladshadow)"
tail -n 3 logs/fundlog.log
ls -la logs/funding_*.csv 2>/dev/null || true
rm -f /tmp/fundlog_ui_patch.py /tmp/fundlog.service
