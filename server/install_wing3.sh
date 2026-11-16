#!/bin/bash
# 16-Nov-2026: autosize also keeps the guard size limits in step with the base (only while a ceiling is set). No service restart needed.
set -e
REF=${1:-main}
cd ~/deltabot
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/wing3_patch.py -o wing3_patch.py
./venv/bin/python wing3_patch.py
restore() { cp autosize.py.bak1116w3 autosize.py; echo "RESTORED - nothing changed"; exit 1; }
./venv/bin/python -m py_compile autosize.py || restore
./venv/bin/python - <<'P' || restore
import autosize as A
assert A.limits_for(0.06) == dict(max_order_btc=0.18, max_open_btc=0.48)
assert A.limits_for(0.16) == dict(max_order_btc=0.48, max_open_btc=1.28)
assert A.limits_for(0.01) == dict(max_order_btc=0.05, max_open_btc=0.15)
n = 1794900000.0; st = dict(last_set=0.06, ceiling=0.30, ceiling_from_ts=n - 1)
assert A.decide(6000.0, 375.0, 0.06, True, st, n)["base"] == 0.16
assert A.decide(9000.0, 375.0, 0.16, True, dict(st, last_set=0.16), n)["base"] == 0.24
assert A.decide(20000.0, 375.0, 0.16, True, dict(st, last_set=0.16), n)["base"] == 0.30
assert A.decide(3000.0, 375.0, 0.16, True, dict(st, last_set=0.16), n)["base"] == 0.08
print("CHECK OK: base follows the balance up and down, limits follow the base")
P
echo "WING3 INSTALL DONE"
