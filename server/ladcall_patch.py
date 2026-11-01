# 1-Nov-2026: paper ladder bots (bot.py v9, variants.py v10/v11/v12) get the CE leg (ladcall.py, v9 CALL v3 rules with
# Smart Sell). The hook runs at the end of every running paper step; the STOP button also buys back open calls.
# Idempotent; backups *.bak_lc. Paper only.
import sys, os
HOME = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
HOOK = '''{i}try:
{i}    import ladcall
{i}    ladcall.tick_for(self, getattr(self, "key", "ladder"), now, bid, ask, mark)
{i}except Exception as _e:
{i}    log.error("call leg %s: %s", getattr(self, "key", "ladder"), _e)
'''
SQ = '''        try:
            import ladcall
            ladcall.squareoff_for(getattr(self, "key", "ladder"), self.clock(), self.feed.ticker()[2])
        except Exception as _e:
            log.error("call leg stop: %s", _e)
'''
def patch(f, reps):
    p = os.path.join(HOME, f)
    s = open(p, encoding="utf-8").read()
    if "ladcall" in s:
        print(f, "already patched"); return
    for a, b in reps:
        if s.count(a) != 1:
            raise SystemExit("ANCHOR PROBLEM in %s (%d hits): %r - nothing written" % (f, s.count(a), a[:60]))
        s = s.replace(a, b)
    if not os.path.exists(p + ".bak_lc"):
        os.replace(p, p + ".bak_lc")
    open(p, "w", encoding="utf-8").write(s)
    print("patched", f)

patch("bot.py", [("        self.maybe_reports(now, mark)\n        self.save()\n",
                  "        self.maybe_reports(now, mark)\n" + HOOK.format(i="        ") + "        self.save()\n"),
                 ("    def handle_squareoff(self):\n        L = self.ladder\n",
                  "    def handle_squareoff(self):\n        L = self.ladder\n" + SQ)])
patch("variants.py", [("            self.maybe_reports(now, mark)\n            self.save()\n",
                       "            self.maybe_reports(now, mark)\n" + HOOK.format(i="            ").replace("log.error", "bot.log.error") + "            self.save()\n")])
