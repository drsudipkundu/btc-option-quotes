#!/bin/bash
# 21-Nov-2026: signal logger (read-only, public data only, no keys, no orders). Saves BTC open interest, long/short ratio,
# funding, DVOL, Fear & Greed hourly (cron :05) and every liquidation live (service "signalliq") -> logs/signal/*.csv.
# Also adds logs/signal to the daily Drive sync. No trading bot is touched or restarted.
set -e
cd ~/deltabot
REF=${1:-main}
BASE=https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server
for f in signal_logger.py signal_liq.py drivesync.sh; do curl -fsSL $BASE/$f -o $f.new; done
python3 -m py_compile signal_logger.py.new signal_liq.py.new
bash -n drivesync.sh.new
cp drivesync.sh drivesync.sh.bak1121 2>/dev/null || true
mv signal_logger.py.new signal_logger.py; mv signal_liq.py.new signal_liq.py; mv drivesync.sh.new drivesync.sh; chmod +x drivesync.sh
mkdir -p logs/signal
./venv/bin/pip install -q websockets
echo "--- first pass (read-only, pulls ~30 days):"
./venv/bin/python signal_logger.py 2>&1 | tail -n 20
( crontab -l 2>/dev/null | grep -v signal_logger.py; echo "5 * * * * cd $HOME/deltabot && ./venv/bin/python signal_logger.py >> logs/signal/logger.log 2>&1" ) | crontab -
cat > /tmp/signalliq.service <<UNIT
[Unit]
Description=Liquidation recorder - Binance and Bybit BTCUSDT public streams (read-only)
After=network-online.target
[Service]
User=$USER
WorkingDirectory=$HOME/deltabot
ExecStart=$HOME/deltabot/venv/bin/python $HOME/deltabot/signal_liq.py
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
sudo cp /tmp/signalliq.service /etc/systemd/system/signalliq.service
sudo systemctl daemon-reload
sudo systemctl enable --now signalliq
sleep 5
echo "signalliq: $(systemctl is-active signalliq)  deltabot: $(systemctl is-active deltabot)  nightlive: $(systemctl is-active nightlive)  ui: $(systemctl is-active ui)"
ls -la logs/signal/
rm -f /tmp/signalliq.service
