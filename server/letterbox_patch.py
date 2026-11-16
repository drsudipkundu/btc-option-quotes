#!/usr/bin/env python3
"""letterbox_patch (16-Nov-2026): nightwatch.py learns the extra Telegram commands /hedge /base /log /services /clearhalt /exit
(done by letterbox.py). Every edit must match exactly once, otherwise nothing is written. Backup nightwatch.py.bak1116lb"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
EDITS = [
 ('''        elif c in ("/help", "/start"):''', '''        elif c.split()[0] in __import__("letterbox").TG_CMDS:
            try:
                import letterbox as LB
                tg_send(LB.telegram(c, st)[:3800])
            except Exception as e:
                tg_send("Command failed (%s)." % type(e).__name__)
        elif c in ("/help", "/start"):'''),
 ('''ack = pause repeated alerts 30 min | /help")''', '''ack = pause repeated alerts 30 min | /hedge = hedge now, /hedge on, /hedge off | "
        "/base = base and automatic size | /log = last trades | /services = are the bots running | /clearhalt | "
        "/exit = buy back everything now (asks to confirm) | /install = update waiting for your yes | "
        "/orders | /fills | /quote SYMBOL | /chain c or p | /help")'''),
]
OLD_TUPLES = ('''("/hedge", "/base", "/log", "/services", "/clearhalt", "/exit"):''', '''("/hedge", "/base", "/log", "/services", "/clearhalt", "/exit", "/install"):''')
p = os.path.join(H, "nightwatch.py"); s = open(p).read()
if "import letterbox as LB" in s:
    done = False
    for t in OLD_TUPLES:                                   # earlier versions listed the commands here; now letterbox.py holds the list
        if s.count("c.split()[0] in " + t) == 1:
            s = s.replace("c.split()[0] in " + t, 'c.split()[0] in __import__("letterbox").TG_CMDS:')
            for h in ("(asks to confirm) | /install = update waiting for your yes | /help", "(asks to confirm) | /help"):
                if h in s:
                    s = s.replace(h, "(asks to confirm) | /install | /orders | /fills | /quote SYMBOL | /chain c or p | /help"); break
            open(p + ".tmp", "w").write(s); os.replace(p + ".tmp", p); done = True
            print("nightwatch.py: command list now comes from letterbox.py")
    if not done:
        print("already patched")
    sys.exit(0)
for old, new in EDITS:
    if s.count(old) != 1:
        print("STOP: expected one match, found %d for: %s\nNOTHING WRITTEN" % (s.count(old), old[:70])); sys.exit(1)
    s = s.replace(old, new)
shutil.copy2(p, p + ".bak1116lb"); open(p + ".tmp", "w").write(s); os.replace(p + ".tmp", p)
print("LETTERBOX PATCH DONE (nightwatch.py)")
