#!/bin/bash
# Chart page upgrade (1-Nov-2026): overlay v1.3 (near-price liquidation detail, dynamic order-book bars) put INSIDE the chart page,
# because the jsDelivr link no longer works for new versions (repo over 50 MB). Backup first; re-running is safe.
# Only chartpage.py changes; no keys, no bot code, no orders touched.
set -e
cd ~/deltabot
cp -n chartpage.py chartpage.py.bak3
OVL=0362ca70ca0bc3bca400b6a6a3132cddaf3fa9de
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/main/server/chartpage_patch_strategies.py -o /tmp/chartpage_patch_strategies.py
python3 /tmp/chartpage_patch_strategies.py chartpage.py
curl -fsSL https://raw.githubusercontent.com/drsudipkundu/btc-option-quotes/$OVL/userscripts/botchart-overlay.js -o /tmp/botchart-overlay.js
python3 - <<'PY'
import re
p = 'chartpage.py'
s = open(p, encoding='utf-8').read()
js = open('/tmp/botchart-overlay.js', encoding='utf-8').read()
assert 'v1.3' in js[:200], 'overlay download looks wrong - nothing changed'
import base64
b64 = base64.b64encode(js.encode('utf-8')).decode()   # base64 has no quotes or backslashes, so it is safe inside any Python string
s = re.sub(r'<script src="https://cdn\.jsdelivr\.net/gh/drsudipkundu/btc-option-quotes@[0-9a-f]+/userscripts/botchart-overlay\.js"></script>', '', s)
s = re.sub(r'<script>/\*BCO-START\*/.*?/\*BCO-END\*/</script>', '', s, flags=re.S)
end = '</script></body></html>"""'
assert end in s, 'page end marker not found - nothing changed'
s = s.replace(end, '</script><script>/*BCO-START*/(0,eval)(decodeURIComponent(escape(atob("' + b64 + '"))));/*BCO-END*/</script></body></html>"""')
open(p, 'w', encoding='utf-8').write(s)
print('overlay v1.3 placed inside the page')
PY
python3 -m py_compile chartpage.py
sudo systemctl restart ui
sleep 3
systemctl is-active ui
