#!/usr/bin/env python3
"""hedgerule_patch (19-Nov-2026, Sudip 12:57 "All yes. 3 yes"). Needs livefl_patch first (run by install_livefl.sh after it).
3) hedge-exists rule, both sides: the live trend leg is sized UP (x1.5) only if a far option beyond its strike (same expiry,
   on offer, ask <= wing_max x the sale bid) exists at the sale; otherwise it stays 1x. Half size on no-flag nights is unchanged.
   Reason: Delta's daily puts usually stop 3-5 % below BTC, so the put hedge was impossible on 17 and 18 Nov.
4) capital formula (sizecalc) counts the live rule's biggest night as 5.5 units while flagmode is f or h (4 when off).
5) hedge retry that buys nothing now logs "still no far option on offer" instead of "cost 0.00 USD".
6) "trend leg x" message once per night (paper copies sent it every minute until filled).
Every edit must match exactly once, otherwise NOTHING is written. Backups .bak1119h"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
HEDGE_OK = '''    def hedge_ok(self, o, spot):
        """19-Nov-2026: size-up only when a far option beyond this strike (same expiry) is on offer at the sale"""
        w = float(self.cfg.get("wing") or 0)
        bid = float(o.get("bid") or 0)
        if w <= 0 or bid <= 0:
            return False
        top = float(self.cfg.get("wing_max", 0.5)) * bid
        for c in (self.ch or []):
            if c["typ"] != o["typ"] or c.get("exp") != o.get("exp"):
                continue
            if (c["strike"] > o["strike"]) if o["typ"] == "CE" else (c["strike"] < o["strike"]):
                a = float(c.get("ask") or 0)
                if 0 < a <= top:
                    return True
        return False

'''
EDITS = {
 "nightlogic.py": [
  ('        if mult != 1.0:\n            qty = qty * mult\n',
   '        if mult > 1.0 and callable(getattr(self, "hedge_ok", None)) and not self.hedge_ok(o, spot):\n'
   '            mult = 1.0\n'
   '            note += "; no far option on offer beyond this strike -> no size-up"\n'
   '            if (self.S.get("flags_night") or {}).get("night") == today:\n'
   '                self.S["flags_night"]["mult"] = mult\n'
   '        if mult != 1.0:\n            qty = qty * mult\n'),
  ('            self.notify("%s trend leg x %.1f tonight%s" % (self.lab, mult, "" if str(self.lab).startswith("NLIVE") else " (paper)"), note)\n',
   '            if self.S.get("rich_told") != today:\n'
   '                self.S["rich_told"] = today\n'
   '                self.notify("%s trend leg x %.1f tonight%s" % (self.lab, mult, "" if str(self.lab).startswith("NLIVE") else " (paper)"), note)\n'),
 ],
 "nightlive.py": [
  ('    def _wing_release(self, now, spot):\n', HEDGE_OK + '    def _wing_release(self, now, spot):\n'),
  ('            elif prem > 0:\n                self.log("%s hedge for %s cost',
   '            elif left > 0:\n                self.log("%s hedge retry for %s: still no far option on offer, %d of %d contracts missing" % (self.lab, s["sym"], left, want))\n'
   '            elif prem > 0:\n                self.log("%s hedge for %s cost'),
 ],
 "sizecalc.py": [
  ('    units = 4.0 if lc.get("rule") == "v5asl" else S["v4_max_mult"]',
   '    units = (5.5 if str(lc.get("flagmode", "off")).lower() in ("f", "h") else 4.0) if lc.get("rule") == "v5asl" else S["v4_max_mult"]'),
 ],
}
def main():
    texts = {}
    for f, eds in EDITS.items():
        s = open(os.path.join(H, f), encoding="utf-8").read()
        if "hedge_ok" in s or "rich_told" in s or ("5.5 if" in s and f == "sizecalc.py"):
            print("already applied: " + f); continue
        if f == "nightlive.py" and "flagmode" not in s:
            raise SystemExit("STOP: live flag patch not installed - NOTHING WRITTEN")
        for old, new in eds:
            if s.count(old) != 1:
                raise SystemExit("ANCHOR PROBLEM in %s (%d matches): %r - NOTHING WRITTEN" % (f, s.count(old), old[:70]))
            s = s.replace(old, new)
        texts[f] = s
    for f, s in texts.items():
        shutil.copy(os.path.join(H, f), os.path.join(H, f + ".bak1119h"))
        open(os.path.join(H, f), "w", encoding="utf-8").write(s)
    print("HEDGE RULE PATCH DONE (%d files)" % len(texts))
if __name__ == "__main__":
    main()
