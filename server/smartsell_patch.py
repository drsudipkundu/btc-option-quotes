# 1-Nov-2026: server paper night copies (nightbot.py) sell with Smart Sell (smartsell.py). Idempotent; backup nightbot.py.bak_ss.
import sys, os
HOME = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(HOME, "nightbot.py")
s = open(p, encoding="utf-8").read()
if "SmartNight" in s:
    print("nightbot already has smart sell"); sys.exit(0)
R = [("import control\n", "import control\nfrom smartsell import SmartNight\n"),
     ("self.nights = [Night(v, base", "self.nights = [SmartNight(v, base"),
     ("open_any = any(n.open_legs() for n in self.nights)", "open_any = any(n.open_legs() or n.ss_pending() for n in self.nights)"),
     ('            n.step(now, spot, ch, ind, stopped or c["state"] != "running" or c["mode"] != "paper")\n',
      '            if not (stopped or c["state"] != "running" or c["mode"] != "paper"):\n                n.ss_tick(now, spot, ch)\n'
      '            n.step(now, spot, ch, ind, stopped or c["state"] != "running" or c["mode"] != "paper")\n')]
for a, b in R:
    if s.count(a) != 1:
        raise SystemExit("ANCHOR PROBLEM (%d hits): %r - nothing written" % (s.count(a), a[:60]))
    s = s.replace(a, b)
if not os.path.exists(p + ".bak_ss"):
    os.replace(p, p + ".bak_ss")
open(p, "w", encoding="utf-8").write(s)
print("nightbot smart sell patch applied")
