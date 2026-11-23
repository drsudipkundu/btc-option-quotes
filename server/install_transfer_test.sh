#!/bin/bash
# 23-Nov-2026: one-off TRANSFER TEST. Moves Rs 5,000 (USD 58.82) serverbot -> ladder9, waits 30 min, moves it back (main-account key).
# No orders, no bot restarted, no setting changed. Installs one file and runs it once, detached.
# Order: download -> syntax check -> read-only check (stops here if anything is wrong, nothing moves) -> real test in background.
set -eo pipefail
REF="${1:-main}"
cd ~/deltabot
curl -fsSL "https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/transfer_test.py" -o transfer_test.py.new
./venv/bin/python -m py_compile transfer_test.py.new
mv transfer_test.py.new transfer_test.py
echo "--- read-only check (nothing moves):"
./venv/bin/python transfer_test.py check | tee /tmp/tt_check.txt
if grep -q "^PROBLEMS" /tmp/tt_check.txt; then
  echo "Stopped: the check found a problem, nothing was moved."; exit 1
fi
if ! grep -q "check OK" /tmp/tt_check.txt; then
  echo "Stopped: the check did not finish cleanly, nothing was moved."; exit 1
fi
echo "--- check OK: starting the real test in the background (Telegram messages will follow)"
nohup ./venv/bin/python transfer_test.py run --yes-move >> logs/transfer_test.out 2>&1 &
sleep 2
echo "started. status any time:  ./venv/bin/python transfer_test.py status"
