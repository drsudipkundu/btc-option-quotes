#!/usr/bin/env python3
"""letterbox_patch (16-Nov-2026): nightwatch.py learns the extra Telegram commands /hedge /base /log /services /clearhalt /exit
(done by letterbox.py). Every edit must match exactly once, otherwise nothing is written. Backup nightwatch.py.bak1116lb"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
EDITS = [
 ('''        elif c in ("/help", "/start"):''', '''        elif c.split()[0] in ("/hedge", "/base", "/log", "/services", "/clearhalt", "/exit", "/install"):
            try:
                import letterbox as LB
                tg_send(LB.telegram(c, st)[:3800])
            except Exception as e:
                tg_send("Command failed (%s)." % type(e).__name__)
        elif c in ("/help", "/start"):'''),
 ('''ack = pause repeated alerts 30 min | /help")''', '''ack = pause repeated alerts 30 min | /hedge = hedge now, /hedge on, /hedge off | "
        "/base = base and automatic size | /log = last trades | /services = are the bots running | /clearhalt | "
        "/exit = buy back everything now (asks to confirm) | /install = update waiting for your yes | /help")'''),
]
UPGRADE = ('''("/hedge", "/base", "/log", "/services", "/clearhalt", "/exit"):''', '''("/hedge", "/base", "/log", "/services", "/clearhalt", "/exit", "/install"):''')
p = os.path.join(H, "nightwatch.py"); s = open(p).read()
if "import letterbox as LB" in s:
    if s.count(UPGRADE[0]) == 1:                           # first version installed earlier today: add /install
        open(p + ".tmp", "w").write(s.replace(UPGRADE[0], UPGRADE[1]).replace("(asks to confirm) | /help", "(asks to confirm) | /install = update waiting for your yes | /help")); os.replace(p + ".tmp", p)
        print("nightwatch.py: /install added")
    else:
        print("already patched")
    sys.exit(0)
for old, new in EDITS:
    if s.count(old) != 1:
        print("STOP: expected one match, found %d for: %s\nNOTHING WRITTEN" % (s.count(old), old[:70])); sys.exit(1)
    s = s.replace(old, new)
shutil.copy2(p, p + ".bak1116lb"); open(p + ".tmp", "w").write(s); os.replace(p + ".tmp", p)
print("LETTERBOX PATCH DONE (nightwatch.py)")
