#!/usr/bin/env python3
"""wingretry_patch (18-Nov-2026, Sudip 17-Nov 23:37: "Yes include").
On 17-Nov the put P-BTC-61200 got NO far option: Delta had no offers at the far strikes at 23:31, and the hedge buyer
(smart in price: polite bid, then asking price stepping up to 1.3x, never above 50 % of the sale price) tried only at the sale.
Now: every wing_retry_s (300 s) while a sold option is open and short of its far options, the same smart buy is tried again
for the missing quantity only (strike chosen from the BTC price of that moment). Stops 1 h before expiry, never while crash-guard
insurance is open on that side. "HEDGE NOT COMPLETE" is sent once; a retry that buys sends "HEDGE BOUGHT".
Every edit must match exactly once, otherwise NOTHING is written. Backup: nightlive.py.bak1118w"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
RETRY = '''    def _wing_retry(self, now, spot):
        """sold option short of its far options -> try the smart buy again for the missing part (every wing_retry_s)"""
        if float(self.cfg.get("wing") or 0) <= 0 or now.timestamp() > self.S["exp"] - 3600:
            return False
        if time.time() - getattr(self, "_wing_retry_t", 0) < float(self.cfg.get("wing_retry_s", 300)):
            return False
        self._wing_retry_t = time.time()
        todo = []
        for s in self.open_legs():
            if s["dir"] != "S" or s.get("kind") == "ins":
                continue
            if any(l.get("kind") == "ins" and l["side"] == s["side"] for l in self.open_legs()):
                continue
            have = sum(l["qty"] for l in self.S["legs"] if l.get("kind") == "wing" and l.get("cover") == s["id"])
            miss = round(s["qty"] - have, 3)
            if miss >= C - 1e-9:
                todo.append(dict(s, qty=miss))
        if not todo:
            return False
        n0 = len(self.S["legs"])
        self._wing_quiet = True
        try:
            self._buy_wings(now, spot, todo)
        finally:
            self._wing_quiet = False
        return len(self.S["legs"]) != n0

'''
EDITS = [
 ("wing_sell_every_s=300, juice=0.0,", "wing_sell_every_s=300, wing_retry_s=300, juice=0.0,"),
 ('''    def _wing_release(self, now, spot):
''', RETRY + '''    def _wing_release(self, now, spot):
'''),
 ('''            if left > 0:
                self.notify("%s HEDGE NOT COMPLETE for %s''', '''            if left > 0 and not getattr(self, "_wing_quiet", False):
                self.notify("%s HEDGE NOT COMPLETE for %s'''),
 ('''            changed |= self._juice_exit(now, spot)
''', '''            changed |= self._juice_exit(now, spot)
            changed |= self._wing_retry(now, spot)
'''),
]


def main():
    p = os.path.join(H, "nightlive.py")
    s = open(p).read()
    if "_wing_retry" in s:
        print("nightlive.py: already patched"); return
    if "_juice_exit" not in s:
        print("STOP: juice_patch is not installed - NOTHING WRITTEN"); sys.exit(1)
    for old, new in EDITS:
        if s.count(old) != 1:
            print("STOP: expected exactly one match, found %d, for:\n%s\nNOTHING WRITTEN" % (s.count(old), old[:120])); sys.exit(1)
        s = s.replace(old, new)
    if not os.path.exists(p + ".bak1118w"):
        shutil.copy2(p, p + ".bak1118w")
    open(p + ".tmp", "w").write(s)
    os.replace(p + ".tmp", p)
    print("WING RETRY PATCH DONE")


if __name__ == "__main__":
    main()
