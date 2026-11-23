#!/bin/bash
# 23-Nov-2026: auto size raises the small base straight to what the balance allows (no +0.01/week step). No restart needed.
set -e
REF=${1:-main}
H=$(TZ=Asia/Kolkata date +%H%M)
if [ "$H" -ge 2230 ] || [ "$H" -lt 100 ]; then echo "REFUSED: 22:30-01:00 IST"; exit 1; fi
cd ~/deltabot
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/autosize_direct_patch.py -o autosize_direct_patch.py
./venv/bin/python autosize_direct_patch.py
./venv/bin/python autosize.py --show | tail -3
echo "AUTOSIZE DIRECT INSTALL DONE (takes effect at the 23:22 check)"
