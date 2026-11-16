#!/bin/bash
# harmless drill for the letterbox update path: changes NOTHING, only reports.
echo "HELLO from the server at $(TZ=Asia/Kolkata date '+%d-%b %H:%M IST'). Version asked: ${1:0:7}"
for s in nightlive nightbot shadowbot variantbot ui ladderlive; do echo "$s: $(systemctl is-active $s)"; done
echo "DRILL DONE - nothing was changed"
