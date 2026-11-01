# 1-Nov-2026: control page ui.py changes for (1) health pages with strategy buttons (/health?f=v4|v5, /lhealth?v=v9..v12)
# and (2) the strategy details & compare page (/strategies). Idempotent; backup ui.py.bak_pages. Read-only pages only.
import sys, os
HOME = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(HOME, "ui.py")
s = open(p, encoding="utf-8").read()
if 'pth == "/strategies"' in s:
    print("ui already has the pages patch"); sys.exit(0)
Q = '__import__("urllib.parse").parse.parse_qs(__import__("urllib.parse").parse.urlparse(self.path).query)'
old_h = "            return self.send(200, shadow.page_html())\n"
old_l = "            return self.send(200, ladshadow.page_html())\n"
link = '<a href="/health">&#129658; Parameter health</a>'
route = '        if pth == "/health":\n'
for a in (old_h, old_l, link, route):
    if s.count(a) != 1:
        raise SystemExit("ANCHOR PROBLEM (%d hits): %r - nothing written" % (s.count(a), a[:60]))
s = s.replace(old_h, '            return self.send(200, shadow.page_html((%s.get("f") or ["v4"])[0]))\n' % Q)
s = s.replace(old_l, '            return self.send(200, ladshadow.page_html((%s.get("v") or ["v9"])[0]))\n' % Q)
s = s.replace(link, link + '<a href="/strategies">&#128203; Strategy details &amp; compare</a>')
s = s.replace(route, '        if pth == "/strategies":\n            import stratinfo\n            return self.send(200, stratinfo.page_html())\n' + route)
if not os.path.exists(p + ".bak_pages"):
    os.replace(p, p + ".bak_pages")
open(p, "w", encoding="utf-8").write(s)
print("ui pages patch applied")
