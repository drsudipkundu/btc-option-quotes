#!/bin/bash
# 27-Nov-2026 (Sudip: paper bots realistic for Rs 8.8 L max): sets the brake (max BTC held) of the PAPER ladders lv10-lv15 to 0.16 BTC
# through the same control file the control page uses. Lower brake = no new buys above it; held lots are kept and sold normally.
# Paper only: v9 live runner, night bots and all money are untouched; no restart (paper ladders read the brake every step).
set -eo pipefail
cd ~/deltabot
cp state/control.json state/control.json.bak1127 2>/dev/null || true
./venv/bin/python - <<'PY'
import control
want = 0.16
for k in ("lv10", "lv11", "lv12", "lv13", "lv14", "lv15"):
    if k in control.NAMES:
        control.set_brake(k, want)
        print(k, "brake now", control.brake_for(k))
    else:
        print(k, "not on this server, skipped")
print("ladder (paper v9) brake unchanged:", control.brake_for("ladder"))
PY
echo "PAPERBRAKE INSTALL DONE: paper ladders lv10-lv15 brake 0.16 BTC"
