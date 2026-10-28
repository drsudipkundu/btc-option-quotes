#!/bin/bash
# Adds the chart overlay (volume profile, liquidation clusters, option OI, order-book walls, readout, liquidity POC,
# ladder check) to the My Bots chart page. Makes a backup first; re-running updates it. Only chartpage.py changes
# (one <script> line); no keys, no bot code, no orders touched. The overlay file itself is loaded by the browser from GitHub.
set -e
# overlay version: 2f6af8fb351859fe6e9c467ff1fe83c7c1a6adfd
cd ~/deltabot
cp -n chartpage.py chartpage.py.bak3
python3 - <<'PY'
import re
p = 'chartpage.py'
s = open(p).read()
s = re.sub(r'<script src="https://cdn\.jsdelivr\.net/gh/drsudipkundu/btc-option-quotes@[0-9a-f]+/userscripts/botchart-overlay\.js"></script>', '', s)
end = '</script></body></html>"""'
assert end in s, 'page end marker not found - nothing changed'
tag = '<script src="https://cdn.jsdelivr.net/gh/drsudipkundu/btc-option-quotes@2f6af8fb351859fe6e9c467ff1fe83c7c1a6adfd/userscripts/botchart-overlay.js"></script>'
s = s.replace(end, '</script>' + tag + '</body></html>"""')
open(p, 'w').write(s)
print('chartpage.py patched')
PY
python3 -m py_compile chartpage.py
sudo systemctl restart ui
sleep 3
systemctl is-active ui
