#!/bin/bash
# 24-Nov-2026 c05 (Sudip 13:18 "0.30 ceiling: increase"): automatic-base ceiling 0.30 -> 0.40 BTC. The balance rule still decides the base.
set -e
H=$(TZ=Asia/Kolkata date +%H%M)
if [ "$H" -ge 2230 ] || [ "$H" -lt 100 ]; then echo "REFUSED: 22:30-01:00 IST"; exit 1; fi
cd ~/deltabot
A='        if not (c == 0 or 0.01 <= c <= 0.30):'
B='        if not (c == 0 or 0.01 <= c <= 0.40):'
if grep -qF "$B" autosize.py; then echo "limit already 0.40"; else
  N=$(grep -cF "$A" autosize.py || true)
  if [ "$N" != "1" ]; then echo "STOP: ceiling limit line found $N times - NOTHING CHANGED"; exit 1; fi
  cp autosize.py autosize.py.bak1124c
  ./venv/bin/python - <<'PY'
p="autosize.py"; s=open(p).read()
s=s.replace("        if not (c == 0 or 0.01 <= c <= 0.30):","        if not (c == 0 or 0.01 <= c <= 0.40):").replace("0 (off) or 0.01 to 0.30 BTC","0 (off) or 0.01 to 0.40 BTC")
open(p,"w").write(s)
PY
  ./venv/bin/python -m py_compile autosize.py || { cp autosize.py.bak1124c autosize.py; echo "RESTORED - nothing changed"; exit 1; }
fi
./venv/bin/python autosize.py --ceiling 0.40
./venv/bin/python autosize.py --show | tail -3
echo "CEILING 0.40 INSTALL DONE (used from the 23:22 check)"
