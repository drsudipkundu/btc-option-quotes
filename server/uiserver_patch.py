#!/usr/bin/env python3
"""uiserver_patch (19-Nov-2026): My Bots page gets a 'Server health' tab (/server, module srvhealth.py, read only). Backup ui.py.bak1119s"""
import os, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
f = os.path.join(H, "ui.py"); s = open(f, encoding="utf-8").read()
if "/server" in s:
    print("already applied"); raise SystemExit(0)
E = [('<a href="/health">&#129658; Parameter health</a>', '<a href="/server">&#128421; Server health</a><a href="/health">&#129658; Parameter health</a>'),
     ('        if pth == "/funding":\n', '        if pth == "/server":\n            import srvhealth\n            return self.send(200, srvhealth.page_html())\n        if pth == "/funding":\n')]
for a, b in E:
    if s.count(a) != 1:
        raise SystemExit("ANCHOR PROBLEM (%d matches): %r - NOTHING WRITTEN" % (s.count(a), a[:60]))
    s = s.replace(a, b)
shutil.copy(f, f + ".bak1119s"); open(f, "w", encoding="utf-8").write(s)
print("SERVER HEALTH TAB PATCH DONE")
