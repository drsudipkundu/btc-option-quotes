#!/bin/bash
# 25-Nov-2026 c09 (Sudip 00:24: "just try whether server can mail the code - learning only, do not act on it").
# READ-ONLY: mails nightlive.py and nightlogic.py to Sudip's address as two normal bot mails. Changes nothing, restarts nothing, places no orders.
# Refuses 22:30-01:00 IST or with an open night position (same as every letterbox install). Never mails .env; aborts if a file holds a hard-coded secret.
set -e
cd ~/deltabot
HM=$(TZ=Asia/Kolkata date +%H%M)
if [ "$HM" -ge 2230 ] || [ "$HM" -lt 100 ]; then echo "REFUSED: not between 22:30 and 01:00 IST"; exit 1; fi
OPEN=$(./venv/bin/python -c "import json;d=json.load(open('state/night_nlive.json'));print(sum(1 for l in d.get('legs',[]) if not l.get('closed')))" 2>/dev/null || echo 0)
if [ "$OPEN" != "0" ]; then echo "REFUSED: the live seller has $OPEN open leg(s)"; exit 1; fi
for f in nightlive.py nightlogic.py; do
  [ -f "$f" ] || { echo "MISSING $f"; continue; }
  if grep -iEq "(api_key|api_secret|secret|token|password)[a-z_]*[[:space:]]*=[[:space:]]*['\"][A-Za-z0-9_:\-]{12,}['\"]" "$f"; then echo "ABORT: $f seems to hold a hard-coded secret - not mailed"; exit 1; fi
done
./venv/bin/python - <<'PY'
import os, sys
sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.expanduser("~/deltabot"), ".env"))
import bot
nf = bot.Notifier()
for f in ("nightlive.py", "nightlogic.py"):
    if not os.path.exists(f):
        continue
    t = open(f, encoding="utf-8").read()
    nf._send_now("[CODE COPY] %s (%d lines, %d bytes) - read only" % (f, t.count("\n"), len(t.encode())), t)
    print("mailed", f, len(t))
PY
echo "MAILCODE INSTALL DONE"
