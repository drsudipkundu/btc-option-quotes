#!/usr/bin/env python3
"""topup0230_patch (c31, 27-Nov-2026, Sudip 15:26-15:29: "we are allowing top up qty to be added for 1 hour only. it can be allowed till 0230 hrs" - "both yes").
1. TOP-UP WINDOW: a side may be topped up once ITS far options are bought any time until 02:30 IST (was: within 1 hour of its first sale).
   The time is a setting: "topup_until": "02:30" in state/night_live_cfg.json. All other conditions unchanged (once per side, BTC not past the strike and not
   closer than half the first distance, bid at least 80 % of the first sale price and the floor, no top-up after insurance or a /cut).
2. NIGHT QUANTITY CAP follows the BIG base: default per-night sold / bought cap = 7 x the larger of base and base_big (was 7 x the small base, which a top-up
   to a much bigger big base could have hit). state/limits.json overrides stay as before.
Every edit must match exactly once, else NOTHING is written. Backup nightlive.py.bak1127t"""
import os, sys, shutil

H = os.path.expanduser(os.environ.get("BOT_HOME", "~/deltabot"))
STEP = "    def step(self, now, spot, ch, ind, stopped=False):\n"
HELPER = '''    def _topup_deadline(self, t0):
        """27-Nov-2026: the top-up window ends at cfg topup_until (default 02:30 IST) after the first sale (see topup0230_patch)"""
        hh, mm = str(self.cfg.get("topup_until") or "02:30").split(":")
        d = t0.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if d <= t0:
            d += dt.timedelta(days=1)
        return d

'''
EDITS = [
    ("            late = (now - t0).total_seconds() > 3600\n", "            late = now > self._topup_deadline(t0)\n"),
    ("(now - t_first).total_seconds() > 3600 and all(", "now > self._topup_deadline(t_first) and all("),
    ("(hm >= 2330 or hm < 130) and self.open_legs()", "(hm >= 2330 or hm < 600) and self.open_legs()"),
    ('7 * float(self.cfg.get("base", 0.02))', '7 * max(float(self.cfg.get("base", 0.02)), float(self.cfg.get("base_big") or 0))'),
    ("far options not all bought within 1 hour", "far options not all bought before the top-up window closed"),
    (STEP, HELPER + STEP),
]


def apply(s):
    if "_topup_deadline" in s:
        return None
    for old, new in EDITS:
        if s.count(old) != 1:
            raise SystemExit("STOP: expected exactly one %r, found %d - NOTHING WRITTEN" % (old[:60], s.count(old)))
        s = s.replace(old, new)
    return s


def main():
    p = os.path.join(H, "nightlive.py")
    s = open(p, encoding="utf-8").read()
    n = apply(s)
    if n is None:
        print("already applied"); return
    shutil.copy2(p, p + ".bak1127t")
    open(p + ".tmp", "w", encoding="utf-8").write(n); os.replace(p + ".tmp", p)
    print("TOPUP0230 PATCH DONE")


if __name__ == "__main__":
    main()
