#!/bin/bash
# 24-Nov-2026: ONE yes for the four updates that lapsed because the letterbox holds only one waiting update at a time:
# c01 autosize direct raise, c02 sweep report v2 (report only), c03 refused strike -> next strike, c04 top-up side by side.
REF=${1:-main}
cd ~/deltabot
FAIL=0
for s in install_autosize_direct.sh install_sweep_report2.sh install_refusefix.sh install_topupside.sh; do
  echo "=== $s"
  if curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$s -o state/batch_$s; then
    OUT=$(bash state/batch_$s $REF 2>&1); RC=$?
    echo "$OUT" | tail -n 8
    if [ "$RC" = "0" ]; then echo "RESULT $s: OK"; else echo "RESULT $s: FAILED"; FAIL=1; fi
  else echo "RESULT $s: could not download"; FAIL=1; fi
done
echo "=== summary"
[ "$FAIL" = "0" ] && echo "BATCH 24-NOV DONE: all four installed" || echo "BATCH 24-NOV: at least one FAILED - see above"
exit $FAIL
