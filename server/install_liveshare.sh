#!/bin/bash
# 6-Nov-2026: lets a live ladder (lv13) share the serverbot account with the live night seller + "Live ladder" control page.
# Restarts ONLY the ui (control page). ladderlive and nightlive are NOT restarted (they pick up the changes at their next restart).
# Arms nothing. Run outside 23:25-00:05 IST.
set -e
cd ~/deltabot
REF=${1:-main}
B=https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server
for f in shared_patch.py llive.py llive_ui_patch.py; do curl -fsSL $B/$f -o /tmp/$f; done
cp /tmp/llive.py ~/deltabot/llive.py
python3 /tmp/shared_patch.py ~/deltabot
python3 /tmp/llive_ui_patch.py ~/deltabot
./venv/bin/python -m py_compile ladderlive.py nightbot.py llive.py ui.py
./venv/bin/python -c "import sys; sys.path.insert(0,'.'); import llive; print('llive page bytes:', len(llive.page_html()))"
sudo systemctl restart ui
sleep 5
echo "ui: $(systemctl is-active ui)  ladderlive: $(systemctl is-active ladderlive)  nightlive: $(systemctl is-active nightlive)  nightbot: $(systemctl is-active nightbot)"
./venv/bin/python ladderlive.py --status || true
rm -f /tmp/shared_patch.py /tmp/llive.py /tmp/llive_ui_patch.py
echo "NOTE: nightbot needs a restart later to use the shared-account watcher; do it with the ladderlive restart, outside 23:25-00:05 IST."
