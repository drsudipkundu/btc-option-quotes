#!/bin/bash
# 25-Nov-2026 (step 2 of Sudip's plan, PAPER ONLY): sweep report with the CALLS-OFF switch. Writes only these 5 keys (cap_inr 1 crore = no daily cap in the report, Sudip 26-Nov) into state/sweep_cfg.json:
# calls_on=false, fall_pct=30, ladder_floor_inr=880000 (27-Nov: ladder minimum Rs 8.8 L for now), ladder_max_inr=880000 (Sudip 26-Nov: ladder max Rs 8.8 L; ladder minimum = held-BTC margin + 30% fall reserve, the rest is only REPORTED as excess for serverbot).
# It only READS balances and sends Telegram + e-mail. Install ONLY after the Tradetron call switch-off is confirmed (cc_state=3, no call sold).
# The file has no transfer call, so it cannot move money or place orders. Keeps the 18:15 IST cron line. Order: download both files ->
# syntax check -> offline self-test (stops if anything fails, nothing is replaced) -> replace -> print-only first look.
set -eo pipefail
REF="${1:-main}"
cd ~/deltabot
B="https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server"
curl -fsSL "$B/sweep_report.py" -o sweep_report.py.new
curl -fsSL "$B/selftest_sweep_plus.py" -o selftest_sweep_plus.py.new
./venv/bin/python -m py_compile sweep_report.py.new selftest_sweep_plus.py.new
mkdir -p /tmp/swtest && cp sweep_report.py.new /tmp/swtest/sweep_report.py && cp selftest_sweep_plus.py.new /tmp/swtest/selftest_sweep_plus.py
( cd /tmp/swtest && ~/deltabot/venv/bin/python selftest_sweep_plus.py ) > /tmp/swtest/out.txt 2>&1 || { tail -15 /tmp/swtest/out.txt; echo "Stopped: the self-test failed, nothing was replaced."; exit 1; }
tail -2 /tmp/swtest/out.txt
[ -f sweep_report.py.bak1125 ] || cp sweep_report.py sweep_report.py.bak1125
mv sweep_report.py.new sweep_report.py; mv selftest_sweep_plus.py.new selftest_sweep_plus.py
mkdir -p state
./venv/bin/python - <<'PY'
import json, os
p = os.path.expanduser("~/deltabot/state/sweep_cfg.json")
try:
    c = json.load(open(p))
except Exception:
    c = {}
c.update(calls_on=False, fall_pct=30, ladder_floor_inr=880000, ladder_max_inr=880000, cap_inr=10000000)
json.dump(c, open(p, "w"), indent=1)
print("sweep_cfg.json now:", c)
PY
LINE="15 18 * * * cd ~/deltabot && ./venv/bin/python sweep_report.py >> logs/sweep_report.out 2>&1"
( crontab -l 2>/dev/null | grep -v "sweep_report.py" ; echo "$LINE" ) | crontab -
echo "cron kept (server clock must be IST):"; crontab -l | grep sweep_report
echo "--- first look (print only, no Telegram, no e-mail, nothing moved):"
./venv/bin/python sweep_report.py --show
