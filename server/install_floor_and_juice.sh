#!/bin/bash
# 17-Nov-2026: one approval for two updates: (1) little-premium-left exit at 10 %, (2) capital floor moves with BTC + dollar rate Rs 85.
set -e
REF=${1:-main}
cd ~/deltabot
for f in install_juice.sh install_floor_scale.sh; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
bash install_juice.sh $REF
bash install_floor_scale.sh $REF
echo "BOTH UPDATES DONE"
