#!/usr/bin/env python3
"""richpaper_patch (18-Nov-2026, Sudip: "paper first"): new PAPER copy v5aslp = V5A-CG-SL-P.
Same rules as the paper V5A-CG-SL, one difference: the trend leg (and its IV boost, if any) is sold 1.5 x when tonight's premium
(bid of the trend option as % of BTC) is in the top 10 % of the trend premiums of the last 365 days (state/prem_hist.csv, at least
60 nights of history needed). PAPER ONLY: no order is placed; the live seller's rules (variant v5asl) are untouched - every edit is
inactive unless the copy's name ends with p. Run in ~/deltabot. Every edit must match exactly once, otherwise NOTHING is written.
Backups: <file>.bak1118p"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

RICH = '''    # ---- rich-premium size-up: paper copies whose name ends with p (18-Nov-2026)
    def _rich_qty(self, now, spot, tag, o, qty):
        """trend leg only. Returns (quantity, note). Also keeps the premium history (one line per night)."""
        if not getattr(self, "rich", False) or tag != "trend" or not spot or spot <= 0 or o["bid"] <= 0:
            return qty, ""
        prem = o["bid"] / spot * 100.0
        path = os.path.join(self.home, "state", "prem_hist.csv")
        today = self.S["night"]
        rows = []
        try:
            for r in csv.reader(open(path)):
                if len(r) >= 2 and r[0][:2] == "20":
                    rows.append((r[0], float(r[1])))
        except Exception:
            pass
        lo = (dt.datetime.strptime(today, "%Y-%m-%d") - dt.timedelta(days=365)).strftime("%Y-%m-%d")
        hist = sorted(v for d, v in rows if lo <= d < today)
        note = "premium %.3f %% of BTC; history %d nights" % (prem, len(hist))
        if len(hist) >= RICH_MIN_N:
            x = RICH_PCT * (len(hist) - 1)
            i = int(x)
            thr = hist[i] + (hist[min(i + 1, len(hist) - 1)] - hist[i]) * (x - i)
            note += "; top-10%% line %.3f %%" % thr
            if prem >= thr:
                qty = qty * RICH_MULT
                self.S["rich_night"] = today
                note += " -> RICH: trend leg x %.1f" % RICH_MULT
                self.notify("%s rich premium - trend leg x %.1f (paper)" % (self.lab, RICH_MULT), note)
        if not any(d == today for d, _ in rows):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", newline="") as fh:
                csv.writer(fh).writerow([today, round(prem, 4), "delta bid", o["sym"]])
        self.log("%s %s" % (self.lab, note))
        return qty, note

    # ---- what the rules want tonight
'''

EDITS = {
 "nightlogic.py": [
  ('"v5aslj": "V5A-CG-SL-J"}', '"v5aslj": "V5A-CG-SL-J", "v5aslp": "V5A-CG-SL-P"}\nRICH_MULT, RICH_PCT, RICH_MIN_N = 1.5, 0.90, 60   # v5aslp (paper): trend leg x1.5 when premium is in the top 10 % of the last 365 days'),
  ('        self.jump = variant.endswith("j")\n', '        self.jump = variant.endswith("j")\n        self.rich = variant.endswith("p")\n'),
  ('    # ---- what the rules want tonight\n', RICH),
  ('            leg = self._open(now, spot, tag, p["kind"], p["side"], o, round(p["qty"], 3), "S")\n',
   '            rq, rnote = self._rich_qty(now, spot, tag, o, p["qty"])\n            leg = self._open(now, spot, tag, p["kind"], p["side"], o, round(rq, 3), "S", rnote)\n'),
  ('        bq = self.boost_qty(ind)\n        if bq and "boost" not in S["fired"]:',
   '        bq = self.boost_qty(ind)\n        if bq and getattr(self, "rich", False) and S.get("rich_night") == today:\n            bq = bq * RICH_MULT\n        if bq and "boost" not in S["fired"]:'),
 ],
 "nightbot.py": [('for v in ("v4a", "v5a", "v4asl", "v5asl", "v5aslj")]', 'for v in ("v4a", "v5a", "v4asl", "v5asl", "v5aslj", "v5aslp")]')],
 "control.py": [('"v5aslj", "nlive"', '"v5aslj", "v5aslp", "nlive"')],
 "ui.py": [
  ('    "nlive": ("BTC Night Leg LIVE MONEY', '    "v5aslp": ("BTC Night Leg V5A-CG-SL-P (slope half + rich premium x1.5)", "V5A-CG-SL, but the trend leg is sold 1.5 times when tonight\'s premium (as % of BTC) is in the top 10 % of the last 365 days. Paper only, added 18-Nov-2026. Compare with V5A-CG-SL."),\n    "nlive": ("BTC Night Leg LIVE MONEY'),
  ('for v in ("v4a", "v5a", "v4asl", "v5asl", "v5aslj", "nlive"):', 'for v in ("v4a", "v5a", "v4asl", "v5asl", "v5aslj", "v5aslp", "nlive"):'),
 ],
}


def main():
    out = {}
    for fn, edits in EDITS.items():
        p = os.path.join(H, fn)
        s = open(p).read()
        if "v5aslp" in s:
            print("%s: already patched" % fn); continue
        for old, new in edits:
            if s.count(old) != 1:
                print("STOP: %s: expected exactly one match, found %d, for:\n%s\nNOTHING WRITTEN" % (fn, s.count(old), old[:120])); sys.exit(1)
            s = s.replace(old, new)
        out[p] = s
    for p, s in out.items():
        if not os.path.exists(p + ".bak1118p"):
            shutil.copy2(p, p + ".bak1118p")
        open(p + ".tmp", "w").write(s)
        os.replace(p + ".tmp", p)
    print("RICH PAPER PATCH DONE (%d files)" % len(out))


if __name__ == "__main__":
    main()
