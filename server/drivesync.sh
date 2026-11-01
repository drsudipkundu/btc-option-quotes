#!/bin/bash
# 1-Nov-2026: daily copy of shadow-fleet data from the server straight to Google Drive (rclone remote "gdrive",
# scope drive.file = rclone sees only the files it created). Destination: My Drive/delta_bot_server/.
# Files are first copied to a frozen snapshot (the bots rewrite their state files every few seconds; uploading a
# file that changes mid-upload fails the checksum). Only changed files are uploaded; nothing on Drive is deleted.
# On failure an alert email is sent. Run by cron at 18:05 IST. Manual test: bash drivesync.sh
H=$HOME/deltabot
D=gdrive:delta_bot_server
LOG=$H/logs/drivesync.log
SNAP=$(mktemp -d /tmp/drivesnap.XXXX)
cd $H || exit 1
for p in logs/shadow_nights.csv logs/shadow_nights_v5.csv logs/ladshadow_days.csv state/ladshadow_summary.json \
         logs/shadow state/shadow logs/ladshadow state/ladshadow logs/calls_ladder.csv logs/calls_lv10.csv logs/calls_lv11.csv logs/calls_lv12.csv; do
  [ -e "$p" ] && { mkdir -p "$SNAP/$(dirname $p)"; cp -a "$p" "$SNAP/$p"; }
done
if rclone copy "$SNAP" "$D" --transfers 8 --checkers 8 >>$LOG 2>&1; then
  echo "$(date '+%F %T') drive sync OK" >>$LOG
else
  echo "$(date '+%F %T') drive sync FAILED" >>$LOG
  venv/bin/python -c "
import sys; sys.path.insert(0,'$H')
from dotenv import load_dotenv; load_dotenv('$H/.env')
import bot; bot.Notifier()._send_now('[DeltaBot] Drive sync FAILED', open('$LOG').read()[-3000:])"
fi
rm -rf "$SNAP"
