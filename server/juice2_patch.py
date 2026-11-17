#!/usr/bin/env python3
"""juice2_patch (18-Nov-2026, Sudip 17-Nov 22:33-22:35: "which method is more logical? ... go ahead").
Run in ~/deltabot after juice_patch. Changes the little-premium-left exit to the NET method:
  * night's net credit = premium of every option sold tonight - price paid for every far option (hedge) bought tonight;
  * still to gain by holding = asking price x quantity of the sold options still open
                               - bid x quantity of the far options still open (their resale value, lost if held to expiry);
  * close when still-to-gain <= juice x net credit (juice stays as set, now 5 %). Night with net credit <= 0: rule quiet.
Everything else unchanged. Every edit must match exactly once, otherwise NOTHING is written. Backup: nightlive.py.bak1118j2"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
EDITS = [
 ('''        total = sum(l["entry"] * l["qty"] for l in sold)
        left = 0.0
        for l in opn:
            a = self.cl.ticker(l["sym"])["ask"]
            if a <= 0:
                return False
            left += a * l["qty"]
        if total <= 0 or left > j * total:
            return False''',
  '''        wings = [l for l in self.S["legs"] if l["dir"] == "B" and l.get("kind") == "wing"]
        total = sum(l["entry"] * l["qty"] for l in sold) - sum(l["entry"] * l["qty"] for l in wings)   # net credit
        left = 0.0
        for l in opn:
            a = self.cl.ticker(l["sym"])["ask"]
            if a <= 0:
                return False
            left += a * l["qty"]
        for l in wings:
            if not l["closed"]:
                left -= max(0.0, self.cl.ticker(l["sym"])["bid"]) * l["qty"]   # resale value lost if held
        left = max(0.0, left)
        if total <= 0 or left > j * total:
            return False'''),
 ('''"still to earn at most %.2f USD = %.1f %% of the night's premium %.2f USD (rule: %.0f %%). Buying back %s."''',
  '''"still to gain by holding %.2f USD (sold options' asking price minus far options' resale) = %.1f %% of the night's net credit %.2f USD (rule: %.0f %%). Buying back %s."'''),
]


def main():
    p = os.path.join(H, "nightlive.py")
    s = open(p).read()
    if "# net credit" in s:
        print("nightlive.py: already on the net method"); return
    if "_juice_exit" not in s:
        print("STOP: juice_patch is not installed - NOTHING WRITTEN"); sys.exit(1)
    for old, new in EDITS:
        if s.count(old) != 1:
            print("STOP: expected exactly one match, found %d, for:\n%s\nNOTHING WRITTEN" % (s.count(old), old[:120])); sys.exit(1)
        s = s.replace(old, new)
    if not os.path.exists(p + ".bak1118j2"):
        shutil.copy2(p, p + ".bak1118j2")
    open(p + ".tmp", "w").write(s)
    os.replace(p + ".tmp", p)
    print("JUICE2 PATCH DONE (net credit method; rule level unchanged)")


if __name__ == "__main__":
    main()
