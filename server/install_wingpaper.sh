#!/bin/bash
# 15-Nov-2026: (1) wingpaper.py - PAPER, read-only "far option with every live night sale" tracker, cron every minute.
#              (2) option-book recorder band widened 1-7 % -> 1-12 % out of the money.
# Places no orders, uses no API key, does not touch the live night seller or any other bot file.
set -e
REF=${1:-main}
cd ~/deltabot
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/wingpaper.py -o wingpaper.py.new
./venv/bin/python -m py_compile wingpaper.py.new && mv wingpaper.py.new wingpaper.py
./venv/bin/python wingpaper.py --selftest
./venv/bin/python wingpaper.py
LINE='* * * * * cd /home/ubuntu/deltabot && /home/ubuntu/deltabot/venv/bin/python wingpaper.py >> logs/wingpaper.log 2>&1'
(crontab -l 2>/dev/null | grep -v 'wingpaper.py'; echo "$LINE") | crontab -
echo "cron: $(crontab -l | grep -c wingpaper.py) wingpaper line"
cp recorder/optbook_recorder.py recorder/optbook_recorder.py.bak1115
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/optbook_recorder.py -o recorder/optbook_recorder.py.new
python3 -m py_compile recorder/optbook_recorder.py.new && mv recorder/optbook_recorder.py.new recorder/optbook_recorder.py
python3 -c "import sys; sys.path.insert(0, '$HOME/deltabot/recorder'); import optbook_recorder as R, datetime as dt; s, x = R.pick(dt.datetime.now(R.UTC)); print('recorder band', R.BAND, 'options in band', len(x))"
sudo systemctl restart optbook-recorder
sleep 20
echo "optbook-recorder: $(systemctl is-active optbook-recorder) | nightlive: $(systemctl is-active nightlive)"
cat state/wingpaper.json | cut -c1-200
echo "WINGPAPER INSTALL DONE"
