#!/bin/bash
# 26-Nov-2026 c25: Telegram /stop and /go for the report bots (sweep, emergency, paperboy). Letterbox + the three bot scripts only; NO trading code, NO restart of the night bot.
# Self-tests against the real letterbox.py in a temp folder first; restores backups on any failure. Safe at any hour.
set -eo pipefail
REF="${1:-main}"
cd ~/deltabot; PY=$HOME/deltabot/venv/bin/python
B="https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server"
T=/tmp/bs; rm -rf $T; mkdir -p $T
for f in botstop_patch.py selftest_botstop.py sweep_report.py stagedrel.py entry_shadow.py; do curl -fsSL "$B/$f" -o $T/$f; done
for f in letterbox.py nightlive.py nightlogic.py autosize.py control.py guard.py sizecalc.py nightwatch.py delta_api.py; do [ -f $f ] && cp $f $T/; done
$PY -m py_compile $T/botstop_patch.py $T/sweep_report.py $T/stagedrel.py $T/entry_shadow.py
( cd $T && BOT_HOME=$T/home $PY selftest_botstop.py ) > /tmp/bs_out.txt 2>&1 || { tail -15 /tmp/bs_out.txt; echo "Stopped: self-test failed, nothing was changed."; rm -rf $T; exit 1; }
tail -1 /tmp/bs_out.txt
restore() { for f in letterbox sweep_report stagedrel; do [ -f $f.py.bak1126b ] && cp $f.py.bak1126b $f.py; done; echo "RESTORED the backups - nothing changed"; exit 1; }
cp sweep_report.py sweep_report.py.bak1126b; cp stagedrel.py stagedrel.py.bak1126b
cp $T/botstop_patch.py ./botstop_patch.py
$PY botstop_patch.py || restore
cp $T/sweep_report.py sweep_report.py; cp $T/stagedrel.py stagedrel.py
$PY -m py_compile letterbox.py sweep_report.py stagedrel.py || restore
$PY -c "import letterbox as LB; r = LB.telegram('/stop', {}); print(r[:200]); assert '/stop' in LB.TG_CMDS" || restore
mkdir -p recorder; cp recorder/entry_shadow.py recorder/entry_shadow.py.bak1126b 2>/dev/null || true
cp $T/entry_shadow.py recorder/entry_shadow.py
sudo systemctl restart entry-shadow; sleep 3; echo "entry-shadow: $(systemctl is-active entry-shadow)"
rm -rf $T /tmp/bs_out.txt
echo "BOTSTOP INSTALL DONE: Telegram /stop and /go (sweep, emergency, paperboy, all)"
