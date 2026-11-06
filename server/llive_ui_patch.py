# 6-Nov-2026: control page ui.py - adds the "Live ladder" page (/llive) and its POST actions. Idempotent; backup ui.py.bak_llive.
import sys, os, shutil
HOME = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(HOME, "ui.py")
s = open(p, encoding="utf-8").read()
if 'pth == "/llive"' in s:
    print("ui already has the live ladder page"); sys.exit(0)
link = '<a href="/lhealth">&#129658; Ladder health</a>'
route = '        if pth == "/lhealth":\n'
post = '            elif p == "/deploy":\n'
for a in (link, route, post):
    if s.count(a) != 1:
        raise SystemExit("ANCHOR PROBLEM (%d hits): %r - nothing written" % (s.count(a), a[:60]))
s = s.replace(link, link + '<a href="/llive">&#128308; Live ladder</a>')
s = s.replace(route, '        if pth == "/llive":\n            import llive\n            return self.send(200, llive.page_html())\n' + route)
s = s.replace(post, '            elif p == "/llive":\n                import llive\n                llive.action(q)\n' + post)
if not os.path.exists(p + ".bak_llive"):
    shutil.copy2(p, p + ".bak_llive")
open(p, "w", encoding="utf-8").write(s)
print("ui live ladder page added")
