#!/bin/bash
# 1-Nov-2026: daily copy of shadow-fleet data from the server straight to Google Drive (rclone remote "gdrive",
# scope drive.file = rclone sees only the files it created). Destination: My Drive/delta_bot_server/.
# Only changed files are uploaded; nothing is ever deleted on Drive. On failure an alert email is sent.
# Run by cron at 18:05 IST. Manual test: bash drivesync.sh
H=$HOME/deltabot
D=gdrive:delta_bot_server
LOG=$H/logs/drivesync.log
cd $H || exit 1
ok=1
for p in logs/shadow_nights.csv logs/shadow_nights_v5.csv logs/ladshadow_days.csv state/ladshadow_summary.json; do
  [ -f "$p" ] && { rclone copyto "$p" "$D/$p" >>$LOG 2>&1 || ok=0; }
done
for p in logs/shadow state/shadow logs/ladshadow state/ladshadow; do
  [ -d "$p" ] && { rclone copy "$p" "$D/$p" >>$LOG 2>&1 || ok=0; }
done
if [ $ok = 1 ]; then
  echo "$(date '+%F %T') drive sync OK" >>$LOG
else
  echo "$(date '+%F %T') drive sync FAILED" >>$LOG
  venv/bin/python -c "
import sys; sys.path.insert(0,'$H')
from dotenv import load_dotenv; load_dotenv('$H/.env')
import bot; bot.Notifier()._send_now('[DeltaBot] Drive sync FAILED', open('$LOG').read()[-3000:])"
fi
