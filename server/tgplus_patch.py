#!/usr/bin/env python3
"""tgplus_patch (20-Nov-2026): letterbox.telegram learns /pnl /cum /tonight /guard /paper /server /ceiling (module tgplus.py). Backup letterbox.py.bak1120g"""
import os, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
f = os.path.join(H, "letterbox.py"); s = open(f, encoding="utf-8").read()
if "tgplus" in s:
    print("already applied"); raise SystemExit(0)
E = [('TG_CMDS = ("/hedge", "/base",', 'TG_CMDS = ("/pnl", "/cum", "/tonight", "/guard", "/paper", "/server", "/ceiling", "/hedge", "/base",'),
     ('    ("result", "Last night\'s result and the running total"),\n',
      '    ("result", "Last night\'s result and the running total"),\n'
      '    ("pnl", "Profit of the open position now, leg by leg, plus booked tonight"),\n'
      '    ("cum", "Cumulative: total, week, month, best/worst night, drop from peak"),\n'
      '    ("tonight", "Preview before 23:30: bases, side, flags, strikes listed"),\n'
      '    ("guard", "Each open side: hedged or not, guard mode and firing level"),\n'
      '    ("paper", "Paper copies side by side: profit and nights"),\n'
      '    ("server", "Server health: load, memory, disk, services, backup"),\n'
      '    ("ceiling", "Base ceiling: /ceiling, /ceiling 0.25 then /ceiling yes"),\n'),
     ('    if c == "/hedge":\n',
      '    if c in ("/pnl", "/cum", "/tonight", "/guard", "/paper", "/server", "/ceiling"):\n'
      '        try:\n'
      '            import tgplus as TP\n'
      '            if c == "/ceiling":\n'
      '                return TP.ceiling_cmd(a, st)\n'
      '            return {"/pnl": TP.pnl_text, "/cum": TP.cum_text, "/tonight": TP.tonight_text, "/guard": TP.guard_text,\n'
      '                    "/paper": TP.paper_text, "/server": TP.server_text}[c]()[:3800]\n'
      '        except Exception as e:\n'
      '            return "%s failed: %s %s" % (c, type(e).__name__, str(e)[:150])\n'
      '    if c == "/hedge":\n')]
for a, b in E:
    if s.count(a) != 1:
        raise SystemExit("ANCHOR PROBLEM (%d matches): %r - NOTHING WRITTEN" % (s.count(a), a[:60]))
    s = s.replace(a, b)
shutil.copy(f, f + ".bak1120g"); open(f, "w", encoding="utf-8").write(s)
print("TELEGRAM PLUS PATCH DONE")
