#!/usr/bin/env python3
"""guardrule_patch (19-Nov-2026, Sudip 14:17): crash guard per side for the LIVE seller.
 - side fully covered by its far options (hedge bought): guard stays at 2 x ATR (as before)
 - side NOT fully covered (no far option listed / bought only partly): guard fires when BTC touches the sold strike
   (or at 2 x ATR if that comes first); when the retry later completes the hedge, the guard goes back to 2 x ATR by itself.
 - capital formula (sizecalc): the safer of the hedged and unhedged figure (never below the floor).
Paper copies are unchanged (flag only set by LiveNight). Backups .bak1119g. Every edit must match once or NOTHING is written."""
import os, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
EDITS = {
 "nightlogic.py": [
  ('            lvl = g["ref"] - CG_MULT * g["atr"] if side == "PE" else g["ref"] + CG_MULT * g["atr"]\n            hit = spot <= lvl if side == "PE" else spot >= lvl\n',
   '            lvl = g["ref"] - CG_MULT * g["atr"] if side == "PE" else g["ref"] + CG_MULT * g["atr"]\n'
   '            if getattr(self, "gk_unhedged", False):              # 19-Nov-2026: unhedged side -> guard at the sold strike\n'
   '                sold = [l for l in self.open_legs() if l["dir"] == "S" and l["side"] == side and l.get("kind") != "ins"]\n'
   '                need = sum(l["qty"] for l in sold)\n'
   '                cov = sum(l["qty"] for l in self.open_legs() if l.get("kind") == "wing" and l["side"] == side and l["dir"] == "B")\n'
   '                if sold and cov < need - 1e-9:\n'
   '                    k = max(l["strike"] for l in sold) if side == "PE" else min(l["strike"] for l in sold)\n'
   '                    lvl = max(lvl, k) if side == "PE" else min(lvl, k)\n'
   '                    if g.get("mode") != "strike":\n'
   '                        g["mode"] = "strike"; self.log("%s %s not fully hedged (%.3f of %.3f): crash guard at the sold strike %.0f" % (self.lab, side, cov, need, k))\n'
   '                elif g.get("mode") == "strike":\n'
   '                    g["mode"] = "atr"; self.log("%s %s hedge complete: crash guard back to 2 x ATR (%.0f)" % (self.lab, side, lvl))\n'
   '            hit = spot <= lvl if side == "PE" else spot >= lvl\n'),
 ],
 "nightlive.py": [
  ('        self.rich = False\n        self.flags = False\n        self.noflag_mult = 1.0\n',
   '        self.rich = False\n        self.flags = False\n        self.noflag_mult = 1.0\n        self.gk_unhedged = True               # 19-Nov-2026: guard at the sold strike while a side is not fully hedged\n'),
 ],
 "sizecalc.py": [
  ('    if wing > 0:                                              # always-on hedge: loss is capped at the gap to the far option\n        cap = n * wing\n    else:\n        cap = n * max(0.0, (1 - dist) - (1 - S["ins_beyond"]) * (1 - trig))\n',
   '    cap_g = n * max(0.0, (1 - dist) - (1 - S["ins_beyond"]) * (1 - trig))   # crash-guard loss (no far option)\n'
   '    cap = max(n * wing, cap_g) if wing > 0 else cap_g        # 19-Nov-2026: safer of hedged / unhedged (put hedge often not listed)\n'),
 ],
}
def main():
    texts = {}
    for f, eds in EDITS.items():
        s = open(os.path.join(H, f), encoding="utf-8").read()
        if "gk_unhedged" in s or "cap_g" in s:
            print("already applied: " + f); continue
        for old, new in eds:
            if s.count(old) != 1:
                raise SystemExit("ANCHOR PROBLEM in %s (%d matches): %r - NOTHING WRITTEN" % (f, s.count(old), old[:70]))
            s = s.replace(old, new)
        texts[f] = s
    for f, s in texts.items():
        shutil.copy(os.path.join(H, f), os.path.join(H, f + ".bak1119g"))
        open(os.path.join(H, f), "w", encoding="utf-8").write(s)
    print("GUARD RULE PATCH DONE (%d files)" % len(texts))
if __name__ == "__main__":
    main()
