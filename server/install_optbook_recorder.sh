#!/bin/bash
# 31-Oct-2026: installs the OPTION order-book recorder (public data only; no keys, no orders, bot untouched).
set -e
REF=${1:-main}
mkdir -p ~/deltabot/optbook ~/deltabot/recorder
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/optbook_recorder.py -o ~/deltabot/recorder/optbook_recorder.py
python3 -m py_compile ~/deltabot/recorder/optbook_recorder.py
python3 -c "import sys; sys.path.insert(0, '$HOME/deltabot/recorder'); import optbook_recorder as R, datetime as dt; s, x = R.pick(dt.datetime.now(R.UTC)); print('spot', s, 'options in band', len(x), x[:3])"
sudo tee /etc/systemd/system/optbook-recorder.service >/dev/null <<UNIT
[Unit]
Description=Delta BTC option order-book recorder
After=network-online.target
[Service]
User=$USER
ExecStart=/usr/bin/python3 $HOME/deltabot/recorder/optbook_recorder.py
Restart=always
RestartSec=15
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now optbook-recorder
sleep 30
echo "optbook-recorder: $(systemctl is-active optbook-recorder)"
f=$(ls -t ~/deltabot/optbook/*.jsonl | head -1); echo "$f lines: $(wc -l < $f)"; head -c 400 $f; echo
df -h / | tail -1
