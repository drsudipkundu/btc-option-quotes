# 3-Nov-2026: control page ui.py - adds the read-only "/funding" page (BTCUSD funding rate + real funding paid per account).
# Idempotent; backup ui.py.bak_funding.
import sys, os
HOME = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(HOME, "ui.py")
s = open(p, encoding="utf-8").read()
if 'pth == "/funding"' in s:
    print("ui already has the funding page"); sys.exit(0)
link = '<a href="/lhealth">&#129658; Ladder health</a>'
route = '        if pth == "/lhealth":\n'
for a in (link, route):
    if s.count(a) != 1:
        raise SystemExit("ANCHOR PROBLEM (%d hits): %r - nothing written" % (s.count(a), a[:60]))
s = s.replace(link, link + '<a href="/funding">&#128176; Funding</a>')
s = s.replace(route, '        if pth == "/funding":\n            import fundlog\n            return self.send(200, fundlog.page_html())\n' + route)
if not os.path.exists(p + ".bak_funding"):
    import shutil; shutil.copy2(p, p + ".bak_funding")
open(p, "w", encoding="utf-8").write(s)
print("ui funding page patch applied")
