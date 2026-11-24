#!/usr/bin/env python3
"""remind_patch (c08, 24-Nov-2026, Sudip 23:48 "add a Telegram reminder at 22:30 on any night when sales are still stopped").
Adds a sales-stopped reminder to the nightlive loop: at 22:30 and again at 23:10 IST, if night sales are NOT running
(stopped / paused with /exit or /pause, the STOP file exists, or not armed), one notify per slot: 'SALES ARE STOPPED - send /resume before 23:30'.
Nothing else changes (no orders, no state). Must match each anchor exactly once, else NOTHING is written. Backup nightlive.py.bak1124t"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
P = os.path.join(H, "nightlive.py")
src = open(P, encoding="utf-8").read()
if "def stopped_reminder(" in src:
    print("already installed"); sys.exit(0)
FUNC = '''def stopped_reminder(now, state, stopf_exists, armed, reminded):
    """24-Nov-2026 c08: text of a 'sales are stopped' reminder due now (22:30 and 23:10 IST), else None. Each slot once per day."""
    hm = now.hour * 100 + now.minute
    if not (2230 <= hm <= 2328):
        return None
    why = []
    if state != "running":
        why.append("state is %s (after /exit or /pause)" % state)
    if stopf_exists:
        why.append("the STOP file exists")
    if not armed:
        why.append("the bot is not armed")
    if not why:
        return None
    slot = "%s-%d" % (now.strftime("%Y%m%d"), 0 if hm < 2310 else 1)
    if slot in reminded:
        return None
    reminded.add(slot)
    return "Tonight's 23:30 sale will NOT happen: " + "; ".join(why) + ". Send /resume in Telegram (then /status) before 23:30."

'''
A1 = "def main():\n"
A2 = "    ind, ind_t, last_chk, fails = None, 0, 0, 0\n"
A3 = "            ctl = control.get(SID)\n"
for a in (A1, A2, A3):
    if src.count(a) != 1:
        print("ANCHOR NOT FOUND exactly once:", repr(a)); sys.exit(1)
src = src.replace(A1, FUNC + A1)
src = src.replace(A2, A2 + "    reminded = set()\n")
src = src.replace(A3, A3 + '''            try:
                _r = stopped_reminder(now, ctl["state"], os.path.exists(STOPF), cfg()["armed"], reminded)
                if _r:
                    notify("%s SALES STOPPED" % n.lab, _r)
            except Exception as e:
                log.warning("reminder failed: %s", e)
''')
shutil.copy(P, P.replace(".py", ".py.bak1124t") if False else P + ".bak1124t") if False else shutil.copy(P, os.path.join(H, "nightlive.py.bak1124t"))
open(P, "w", encoding="utf-8").write(src)
print("remind patch written")
