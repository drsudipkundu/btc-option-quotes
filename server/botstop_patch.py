"""26-Nov-2026 c25: Telegram /stop and /go - switch the report-only bots off and on from the phone (letterbox.py only; no trading code touched).
  /stop                       shows which bots run or are stopped
  /stop sweep | emergency | paperboy | all     stops that bot's NEXT runs (flag in state/bots_off.json)
  /go sweep | emergency | paperboy | all       starts it again
A stopped bot does nothing at its next scheduled run (sweep 18:15, emergency every 2 minutes, paperboy every minute); its own --show still works.
This does NOT stop the night sale: use /pause and /resume for that.
Backup: letterbox.py.bak1126b. Every edit must match exactly once."""
import os, shutil, sys
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

BLOCK = r'''BOTS = {"sweep": "sweep bot (18:15 daily report)", "emergency": "emergency bot (staged margin release)", "paperboy": "entry-time paperboy"}
BOTS_F = os.path.join(os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot")), "state", "bots_off.json")
TG_CMDS = tuple(TG_CMDS) + ("/stop", "/go")
CODES.append(("stop", "Stop a report bot's next runs: /stop sweep, /stop emergency, /stop paperboy, /stop all (/stop alone shows status)"))
CODES.append(("go", "Start a stopped report bot again: /go sweep, /go emergency, /go paperboy, /go all"))


def botswitch(c, a):
    """/stop and /go for the report bots (not the night sale: that is /pause and /resume)"""
    try:
        off = json.load(open(BOTS_F))
    except Exception:
        off = {}
    names = [x.lower() for x in a]
    if not names:
        return ("BOT SWITCHES\n" + "\n".join("%s: %s" % (k, "STOPPED by you" if off.get(k) else "running") for k in BOTS)
                + "\nSend /stop sweep | emergency | paperboy | all, and /go ... to start again. (The night sale itself: /pause and /resume.)")
    if names == ["all"]:
        names = list(BOTS)
    bad = [x for x in names if x not in BOTS]
    if bad:
        return "REFUSED: unknown bot %s. Use sweep, emergency, paperboy or all." % ", ".join(bad)
    for x in names:
        if c == "/stop":
            off[x] = int(time.time())
        else:
            off.pop(x, None)
    os.makedirs(os.path.dirname(BOTS_F), exist_ok=True)
    json.dump(off, open(BOTS_F, "w"))
    return "%s: %s. It takes effect at its next run (within 2 minutes; the sweep at its next 18:15)." % ("STOPPED" if c == "/stop" else "STARTED", ", ".join(names))


'''
EDITS = [
    ('def codes_text():\n', BLOCK + 'def codes_text():\n'),
    ('    if c == "/install":\n', '    if c in ("/stop", "/go"):\n        return botswitch(c, a)\n    if c == "/install":\n'),
]


def main():
    p = os.path.join(H, "letterbox.py")
    s = open(p).read()
    for old, new in EDITS:
        n = s.count(old)
        if n != 1:
            print("STOP: anchor found %d times, expected 1: %r - NOTHING CHANGED" % (n, old[:50])); sys.exit(1)
    if not os.path.exists(p + ".bak1126b"):
        shutil.copy(p, p + ".bak1126b")
    for old, new in EDITS:
        s = s.replace(old, new)
    open(p, "w").write(s)
    print("letterbox.py patched (backup letterbox.py.bak1126b)")


if __name__ == "__main__":
    main()
