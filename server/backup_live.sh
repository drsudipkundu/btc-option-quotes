#!/bin/bash
# 5-Nov-2026: nightly copy of the bot CODE + live STATE to Google Drive (rclone remote "gdrive", scope drive.file).
# Why: the core bot files (bot.py, guard.py, nightbot.py, ui.py ...) exist only on the server and in AWS snapshots.
# This puts an independent copy on Drive every night. Never copies secrets: .env and rclone.conf are excluded.
# Seven rotating files (backup_Mon.tar.gz ... backup_Sun.tar.gz) so nothing is ever deleted and Drive never fills.
# Run by cron at 18:20 IST. Manual test: bash backup_live.sh
H=$HOME/deltabot
LOG=$H/logs/backup_live.log
DAY=$(date +%a)
OUT=/tmp/backup_$DAY.tar.gz
cd $H || exit 1
mkdir -p /tmp/bl_units && cp /etc/systemd/system/*.service /tmp/bl_units/ 2>/dev/null
crontab -l > /tmp/bl_units/crontab.txt 2>/dev/null
# state files are rewritten every few seconds, so tar from a frozen copy
SNAP=$(mktemp -d /tmp/blsnap.XXXX)
cp -a --parents *.py *.sh state "$SNAP"/ 2>/dev/null
cp -a --parents logs/*live*.csv logs/trades_live_* logs/funding_*.csv logs/calls_*.csv "$SNAP"/ 2>/dev/null
cp -a /tmp/bl_units "$SNAP"/system_units
rm -rf "$SNAP"/state/shadow "$SNAP"/state/ladshadow          # already copied by drivesync.sh
tar -czf "$OUT" --exclude='.env' --exclude='*.pem' --exclude='rclone.conf' -C "$SNAP" . 2>>$LOG
SZ=$(du -h "$OUT" | cut -f1)
if tar -tzf "$OUT" >/dev/null 2>>$LOG && rclone copyto "$OUT" "gdrive:delta_bot_server/backup_code_state/backup_$DAY.tar.gz" >>$LOG 2>&1; then
  echo "$(date '+%F %T') backup OK $DAY ($SZ)" >>$LOG
else
  echo "$(date '+%F %T') backup FAILED" >>$LOG
  venv/bin/python -c "
import sys; sys.path.insert(0,'$H')
from dotenv import load_dotenv; load_dotenv('$H/.env')
import bot; bot.Notifier()._send_now('[DeltaBot] code+state backup FAILED', open('$LOG').read()[-3000:])"
fi
rm -rf "$SNAP" /tmp/bl_units "$OUT"
