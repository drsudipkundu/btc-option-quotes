#!/bin/bash
# 5-Nov-2026: server safety net. New service "watchdog" (read-only; never trades, no bot is touched or restarted) +
# nightly code/state backup to Drive (cron 18:20 IST). Usage: bash install_watchdog.sh <commit>
# Optional: put  HC_PING_URL=https://hc-ping.com/<your-uuid>  in ~/deltabot/.env (type it yourself with nano) for the
# outside dead-man's-switch; the watchdog picks it up within a minute of the next restart.
set -e
cd ~/deltabot
REF=${1:-main}
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/watchdog.py -o watchdog.py
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/backup_live.sh -o backup_live.sh
./venv/bin/python -m py_compile watchdog.py
bash -n backup_live.sh
echo "--- first read-only pass (no email, no ping side effects except the outside ping if configured):"
./venv/bin/python watchdog.py --once
cat > /tmp/watchdog.service <<UNIT
[Unit]
Description=Server watchdog - checks services, disk, memory, Delta API, sync; pings outside dead-man switch (read-only)
After=network-online.target
[Service]
User=$USER
WorkingDirectory=$HOME/deltabot
ExecStart=$HOME/deltabot/venv/bin/python $HOME/deltabot/watchdog.py
Restart=always
RestartSec=20
[Install]
WantedBy=multi-user.target
UNIT
sudo cp /tmp/watchdog.service /etc/systemd/system/watchdog.service
sudo systemctl daemon-reload
sudo systemctl enable --now watchdog
# nightly backup, 18:20 IST (after the 18:05 drivesync); keeps any other cron lines
( crontab -l 2>/dev/null | grep -v backup_live.sh ; echo "20 18 * * * flock -n /tmp/backup_live.lock bash \$HOME/deltabot/backup_live.sh" ) | crontab -
echo "--- backup test run now:"
bash backup_live.sh && tail -n 2 logs/backup_live.log
sleep 3
echo "watchdog: $(systemctl is-active watchdog)  nightlive: $(systemctl is-active nightlive)  ui: $(systemctl is-active ui)"
tail -n 3 logs/watchdog.log
rm -f /tmp/watchdog.service
