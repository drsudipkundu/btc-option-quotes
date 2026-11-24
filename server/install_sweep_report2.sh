#!/bin/bash
# 24-Nov-2026: upgrades the REPORT-ONLY daily sweep (sweep_report.py v2): adds the serverbot "whole multiple + cushion" check and the
# main-account pocket check. Step follows BTC (live safe balance per 0.01). It only READS balances and sends Telegram + e-mail.
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
[ -f sweep_report.py.bak1124 ] || cp sweep_report.py sweep_report.py.bak1124
mv sweep_report.py.new sweep_report.py; mv selftest_sweep_plus.py.new selftest_sweep_plus.py
LINE="15 18 * * * cd ~/deltabot && ./venv/bin/python sweep_report.py >> logs/sweep_report.out 2>&1"
( crontab -l 2>/dev/null | grep -v "sweep_report.py" ; echo "$LINE" ) | crontab -
echo "cron kept (server clock must be IST):"; crontab -l | grep sweep_report
echo "--- first look (print only, no Telegram, no e-mail, nothing moved):"
./venv/bin/python sweep_report.py --show
