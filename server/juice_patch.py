#!/usr/bin/env python3
"""juice_patch (17-Nov-2026, Sudip: "close everything once the remaining possible gain falls below 10 % of the night's total premium").
Run in ~/deltabot. Behaviour-neutral until state/night_live_cfg.json gets juice > 0  (`nightlive.py --juice 10` = 10 %, `--juice 0` = off).

The rule, for the LIVE night seller only:
  * night's premium  = sum of (sale price x quantity) of every option sold this night (far options and crash-guard insurance not counted);
  * what is left     = sum of (asking price now x quantity) of the sold options still open = the most that can still be earned;
  * when what is left <= juice x night's premium, every sold option still open is bought back at once (at the asking price, never above
    1.1 x it); the far options are then sold by the existing rule (if anybody bids) and the night ends.
With one sold option only this is the same as its resting 10 % order, so nothing changes there; it matters when one option has
closed and the other lingers, or after a boost sale.
Not checked during the sale window (23:30-23:59), not when crash-guard insurance is open, not without an asking price on every open sold
option. Checked at most once a minute. Paper copies, shadow fleets and data collection are untouched.
Every edit must match exactly once, otherwise NOTHING is written. Backup: nightlive.py.bak1117j"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

JUICE = '''    # ------------------------------------------------ little premium left -> close the night (17-Nov-2026)
    def _juice_exit(self, now, spot):
        j = float(self.cfg.get("juice") or 0)
        hm = now.hour * 100 + now.minute
        if j <= 0 or 2330 <= hm <= 2359 or time.time() - getattr(self, "_juice_t", 0) < float(self.cfg.get("juice_every_s", 60)):
            return False
        self._juice_t = time.time()
        sold = [l for l in self.S["legs"] if l["dir"] == "S"]
        opn = [l for l in sold if not l["closed"]]
        if not opn or any(l.get("kind") == "ins" for l in self.open_legs()):
            return False
        total = sum(l["entry"] * l["qty"] for l in sold)
        left = 0.0
        for l in opn:
            a = self.cl.ticker(l["sym"])["ask"]
            if a <= 0:
                return False
            left += a * l["qty"]
        if total <= 0 or left > j * total:
            return False
        self.S["juice_night"] = self.S.get("night")
        self.notify("%s little premium left - closing the night" % self.lab,
                    "still to earn at most %.2f USD = %.1f %% of the night's premium %.2f USD (rule: %.0f %%). Buying back %s." % (
                        left, left / total * 100, total, j * 100, ", ".join(l["sym"] for l in opn)))
        for l in opn:
            try:
                self._close(now, spot, l, None, "JUICE")
            except Exception as e:
                self.notify("%s close error" % self.lab, "%s: %s" % (l["sym"], e))
        self.save()
        return True

'''

EDITS = [
 ("wing_sell_every_s=300, ins_cap=2.0,", "wing_sell_every_s=300, juice=0.0, juice_every_s=60, ins_cap=2.0,"),
 ('''    # ------------------------------------------------ Night hooks
''', JUICE + '''    # ------------------------------------------------ Night hooks
'''),
 ('''        cap_mult = self.cfg["ue_cap"] if why in ("UE", "STOP") else self.cfg["bb_cap"]''',
  '''        cap_mult = self.cfg["ue_cap"] if why in ("UE", "STOP") else (1.1 if why == "JUICE" else self.cfg["bb_cap"])'''),
 ('''        changed |= self.tp_poll(now)
        if now.timestamp() < self.S["exp"] - 900:
            changed |= self._wing_release(now, spot)''',
  '''        changed |= self.tp_poll(now)
        if now.timestamp() < self.S["exp"] - 900:
            changed |= self._juice_exit(now, spot)
            changed |= self._wing_release(now, spot)'''),
 ('''            self._finish(now, "closed early (resting buy-back at 10 pc%s)" % (''',
  '''            self._finish(now, "closed early (%s%s)" % ("little premium left" if self.S.get("juice_night") == self.S.get("night") else "resting buy-back at 10 pc", '''),
 ('''    ap.add_argument("--wing", type=float, metavar="PCT", help="always-on hedge: far option PCT %% beyond every sold strike; 0 = off")
''', '''    ap.add_argument("--wing", type=float, metavar="PCT", help="always-on hedge: far option PCT %% beyond every sold strike; 0 = off")
    ap.add_argument("--juice", type=float, metavar="PCT", help="close the night when at most PCT %% of the night's premium is left to earn; 0 = off")
'''),
 ('''    if a.wing is not None:''', '''    if a.juice is not None:
        if not (a.juice == 0 or 2 <= a.juice <= 40):
            print("REFUSED: give 0 (off) or a percent between 2 and 40"); return
        print("little-premium-left exit:", put_cfg(juice=round(a.juice / 100.0, 4)), "(used at once; no restart needed)"); return
    if a.wing is not None:'''),
]


def main():
    p = os.path.join(H, "nightlive.py")
    s = open(p).read()
    if "_juice_exit" in s:
        print("nightlive.py: already patched"); return
    if "_wing_release" not in s:
        print("STOP: the hedge patches (wing, wing2) are not installed - NOTHING WRITTEN"); sys.exit(1)
    for old, new in EDITS:
        if s.count(old) != 1:
            print("STOP: expected exactly one match, found %d, for:\n%s\nNOTHING WRITTEN" % (s.count(old), old[:120])); sys.exit(1)
        s = s.replace(old, new)
    if not os.path.exists(p + ".bak1117j"):
        shutil.copy2(p, p + ".bak1117j")
    open(p + ".tmp", "w").write(s)
    os.replace(p + ".tmp", p)
    print("JUICE PATCH DONE (rule stays OFF until: venv/bin/python nightlive.py --juice 10)")


if __name__ == "__main__":
    main()
