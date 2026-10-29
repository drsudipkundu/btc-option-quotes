# Adds the "Parameter health" tab (shadow fleet page) to ~/deltabot/ui.py. Idempotent; backup ui.py.bak11.
import sys, os
p = os.path.join(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot"), "ui.py")
s = open(p, encoding="utf-8").read()
if 'pth == "/health"' in s:
    print("ui already has the health tab"); sys.exit(0)
a = '<a href="/chart">&#128200; Chart &amp; options</a>'
b = '        if pth == "/chart":\n'
assert s.count(a) == 1 and s.count(b) == 1, "anchor problem - nothing changed"
s = s.replace(a, '<a href="/health">&#129658; Parameter health</a>' + a)
s = s.replace(b, '        if pth == "/health":\n            import shadow\n            return self.send(200, shadow.page_html())\n' + b)
if not os.path.exists(p + ".bak11"):
    os.replace(p, p + ".bak11")
open(p, "w", encoding="utf-8").write(s)
print("ui health tab added")
