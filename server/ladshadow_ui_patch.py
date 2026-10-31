# Adds the "Ladder health" tab (ladder shadow fleet page /lhealth) to ~/deltabot/ui.py. Idempotent; backup ui.py.bak_lsh.
import sys, os
p = os.path.join(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot"), "ui.py")
s = open(p, encoding="utf-8").read()
if 'pth == "/lhealth"' in s:
    print("ui already has the ladder health tab"); sys.exit(0)
a = '<a href="/health">&#129658; Parameter health</a>'
b = '        if pth == "/health":\n'
assert s.count(a) == 1 and s.count(b) == 1, "anchor problem - nothing changed"
s = s.replace(a, a + '<a href="/lhealth">&#129658; Ladder health</a>')
s = s.replace(b, '        if pth == "/lhealth":\n            import ladshadow\n            return self.send(200, ladshadow.page_html())\n' + b)
if not os.path.exists(p + ".bak_lsh"):
    os.replace(p, p + ".bak_lsh")
open(p, "w", encoding="utf-8").write(s)
print("ui ladder health tab added")
