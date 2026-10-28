#!/bin/bash
# Chart page upgrade (28-Oct-2026): overlay v1.2 (strategy dropdown + volume candles) + v11/v12 lines for it.
# Makes a backup first; re-running is safe. Only chartpage.py changes; no keys, no bot code, no orders touched.
set -e
cd ~/deltabot
cp -n chartpage.py chartpage.py.bak3
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/main/server/chartpage_patch_strategies.py -o /tmp/chartpage_patch_strategies.py
python3 /tmp/chartpage_patch_strategies.py chartpage.py
python3 - <<'PY'
import re
p = 'chartpage.py'
s = open(p, encoding='utf-8').read()
s = re.sub(r'<script src="https://cdn\.jsdelivr\.net/gh/drsudipkundu/btc-option-quotes@[0-9a-f]+/userscripts/botchart-overlay\.js"></script>', '', s)
end = '</script></body></html>"""'
assert end in s, 'page end marker not found - nothing changed'
tag = '<script src="https://cdn.jsdelivr.net/gh/drsudipkundu/btc-option-quotes@a14e9def3ecf3b6aed79b1fc1bd2df57a0ab9994/userscripts/botchart-overlay.js"></script>'
s = s.replace(end, '</script>' + tag + '</body></html>"""')
open(p, 'w', encoding='utf-8').write(s)
print('overlay line updated')
PY
python3 -m py_compile chartpage.py
sudo systemctl restart ui
sleep 3
systemctl is-active ui
