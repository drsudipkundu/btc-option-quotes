#!/bin/bash
# 1-Nov-2026: health pages with strategy buttons + v5 shadow fleet + strategy details/compare page.
# Paper / read-only. Touches only shadowbot, ladshadow and ui services. Usage: bash install_pages.sh <commit>
set -e
C=${1:?commit}
H=~/deltabot
R=https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$C/server
H24=$(TZ=Asia/Kolkata date +%H%M)
if [ "$H24" -ge 2230 ] || [ "$H24" -le 100 ]; then echo "STOP: night window 22:30-01:00 IST - run after 01:00"; exit 1; fi
cd $H
for f in shadow.py ladshadow.py healthnav.py stratinfo.py; do [ -f $f ] && cp $f $f.bak_pages_pre || true; done
for f in shadow.py ladshadow.py healthnav.py stratinfo.py pages_ui_patch.py; do curl -fsSL $R/$f -o $f.new; mv $f.new $f; done
venv/bin/python -m py_compile shadow.py ladshadow.py healthnav.py stratinfo.py
venv/bin/python pages_ui_patch.py $H
venv/bin/python -m py_compile ui.py
sudo systemctl restart shadowbot ladshadow ui
sleep 4
systemctl is-active shadowbot ladshadow ui
venv/bin/python shadow.py --check 2>&1 | tail -15
venv/bin/python -c "
import shadow, ladshadow, stratinfo
for n, b in (('health v4', shadow.page_html('v4')), ('health v5', shadow.page_html('v5')), ('lhealth v11', ladshadow.page_html('v11')), ('strategies', stratinfo.page_html())):
    print(n, len(b), 'bytes OK')"
echo INSTALL DONE
