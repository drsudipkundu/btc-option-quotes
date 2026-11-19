#!/bin/bash
# 19-Nov-2026: 'Server health' tab on the My Bots page (read only). Restarts only the ui service; trading untouched.
set -e
REF=${1:-main}
cd ~/deltabot
for f in srvhealth.py uiserver_patch.py; do curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$REF/server/$f -o $f; done
cp ui.py ui.py.bak1119s2
./venv/bin/python uiserver_patch.py || { cp ui.py.bak1119s2 ui.py; echo "RESTORED"; exit 1; }
./venv/bin/python -m py_compile ui.py srvhealth.py || { cp ui.py.bak1119s2 ui.py; echo "RESTORED"; exit 1; }
./venv/bin/python -c "import srvhealth; b = srvhealth.page_html(); print('page builds:', len(b), 'bytes')" || { cp ui.py.bak1119s2 ui.py; echo "RESTORED"; exit 1; }
sudo systemctl restart ui
sleep 4
echo "ui: $(systemctl is-active ui)"
echo "SERVER HEALTH TAB INSTALL DONE"
