#!/usr/bin/env python3
"""paperplus_patch (19-Nov-2026, Sudip 21:55: every variable to be tested goes on paper now; record any data needed).
Paper copies added (nightbot):
  v5aslk  V5A-CG-SL-K   flags off, crash guard at the sold strike (paper has no far options -> every side unhedged)  = ranking #2 fallback
  v5asl15 V5A-CG-SL-G15 flags off, crash guard at 1.5 x ATR (guard-level comparison with V5A-CG-SL 2 x ATR and -K)
  v5aslhk V5A-CG-SL-HK  flags H + hedge-exists check on the real chain (far put <= 30 %, far call <= 50 % of the bid) + guard at strike
Recorders (live seller):
  logs/postfill_prices.csv  : every 5 min after a resting 90 % buy-back fill, the option's bid/ask until expiry (10 % vs 5 % study)
  logs/hedge_exists.csv     : once per night after the sale, per side: sold strike, far options listed / on offer, cheapest ask, ask nearest 4 %
  crash-guard insurance rows now say which mode fired it (strike or atr) - live and paper
Every edit must match exactly once, else NOTHING is written. Backups .bak1120p"""
import os, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
PAPER_OK = '''    def _paper_hedge_ok(self, o, spot):
        """paper twin of the live hedge-exists rule: a far option beyond this strike on offer at <= 30 % (put) / 50 % (call) of the bid"""
        bid = float(o.get("bid") or 0)
        if bid <= 0:
            return False
        top = (0.3 if o["typ"] == "PE" else 0.5) * bid
        for c in (getattr(self, "ch", None) or []):
            if c["typ"] != o["typ"] or c.get("exp") != o.get("exp"):
                continue
            if (c["strike"] > o["strike"]) if o["typ"] == "CE" else (c["strike"] < o["strike"]):
                a = float(c.get("ask") or 0)
                if 0 < a <= top:
                    return True
        return False

    # ---- persistence
'''
RECORD = '''    def _record(self, now, spot, ch):
        """19-Nov-2026 recorders: option price after a 90 % buy-back fill; far-option availability once per night"""
        import csv
        try:
            if time.time() - getattr(self, "_pf_t", 0) >= 300 and self.S.get("postfill"):
                self._pf_t = time.time()
                p = os.path.join(self.home, "logs", "postfill_prices.csv"); new = not os.path.exists(p)
                with open(p, "a", newline="") as f:
                    w = csv.writer(f)
                    if new: w.writerow(["time_ist", "night", "sym", "sold_at", "bought_back_at", "bid", "ask", "spot"])
                    for x in self.S["postfill"]:
                        if x.get("night") != self.S.get("night"): continue
                        t = self.cl.ticker(x["sym"])
                        w.writerow([now.strftime("%Y-%m-%d %H:%M"), x["night"], x["sym"], x["entry"], x["bb"], t.get("bid"), t.get("ask"), round(spot, 1)])
            if self.S.get("night") and self.S.get("hx_logged") != self.S.get("night") and any(l["dir"] == "S" for l in self.open_legs()):
                self.S["hx_logged"] = self.S["night"]
                p = os.path.join(self.home, "logs", "hedge_exists.csv"); new = not os.path.exists(p)
                with open(p, "a", newline="") as f:
                    w = csv.writer(f)
                    if new: w.writerow(["time_ist", "night", "side", "sold_strike", "spot", "far_listed", "far_on_offer", "cheapest_ask", "ask_near_4pc_strike", "ask_near_4pc", "sold_bid"])
                    for side in ("PE", "CE"):
                        sold = [l for l in self.open_legs() if l["dir"] == "S" and l["side"] == side and l.get("kind") != "ins"]
                        if not sold: continue
                        K = max(l["strike"] for l in sold) if side == "PE" else min(l["strike"] for l in sold)
                        far = [c for c in ch if c["typ"] == side and ((c["strike"] < K) if side == "PE" else (c["strike"] > K))]
                        off = [c for c in far if float(c.get("ask") or 0) > 0]
                        tgt = K - 0.04 * spot if side == "PE" else K + 0.04 * spot
                        n4 = min(far, key=lambda c: abs(c["strike"] - tgt)) if far else None
                        sb = next((float(c.get("bid") or 0) for c in ch if c["typ"] == side and c["strike"] == K), "")
                        w.writerow([now.strftime("%Y-%m-%d %H:%M"), self.S["night"], side, K, round(spot, 1), len(far), len(off),
                                    min((float(c["ask"]) for c in off), default=""), n4["strike"] if n4 else "", (n4.get("ask") if n4 else ""), sb])
        except Exception as e:
            self.log("recorder failed: %s" % e)

    def step(self, now, spot, ch, ind, stopped=False):
        self.cfg = cfg()
'''
EDITS = {
 "nightlogic.py": [
  ('"v5aslh": "V5A-CG-SL-H"}', '"v5aslh": "V5A-CG-SL-H", "v5aslk": "V5A-CG-SL-K", "v5asl15": "V5A-CG-SL-G15", "v5aslhk": "V5A-CG-SL-HK"}'),
  ('        self.flags = len(variant) == 6 and variant[-1] in ("f", "h")\n        self.noflag_mult = NOFLAG_MULT if variant.endswith("h") else 1.0\n',
   '        self.flags = len(variant) >= 6 and variant[5] in ("f", "h")\n        self.noflag_mult = NOFLAG_MULT if variant[5:6] == "h" else 1.0\n'
   '        self.gk_unhedged = variant.endswith("k")       # 19-Nov paper: guard at the sold strike (no far options on paper)\n'
   '        self.cg_mult = 1.5 if variant.endswith("15") else CG_MULT\n'
   '        if variant == "v5aslhk":\n            self.hedge_ok = self._paper_hedge_ok\n'),
  ('    # ---- persistence\n', PAPER_OK),
  ('            lvl = g["ref"] - CG_MULT * g["atr"] if side == "PE" else g["ref"] + CG_MULT * g["atr"]\n',
   '            cgm = getattr(self, "cg_mult", CG_MULT)\n            lvl = g["ref"] - cgm * g["atr"] if side == "PE" else g["ref"] + cgm * g["atr"]\n'),
  ('                             "trigger %.1f hit at spot %.1f; fallback=%d" % (lvl, spot, fb)) if o else None\n',
   '                             "trigger %.1f (%s) hit at spot %.1f; fallback=%d" % (lvl, g.get("mode", "atr"), spot, fb)) if o else None\n'),
  ('        """now: aware datetime (IST). ch: parsed option list for the relevant expiry. ind: indicators."""\n',
   '        """now: aware datetime (IST). ch: parsed option list for the relevant expiry. ind: indicators."""\n        if ch:\n            self.ch = ch\n'),
 ],
 "nightlive.py": [
  ('        self.row(now, "EXIT-90PCT", dict(leg, qty=round(part, 3)), avg, fe, pnl, "live resting limit buy-back")\n',
   '        self.row(now, "EXIT-90PCT", dict(leg, qty=round(part, 3)), avg, fe, pnl, "live resting limit buy-back")\n'
   '        if not any(x["sym"] == leg["sym"] for x in self.S.setdefault("postfill", [])):\n'
   '            self.S["postfill"] = [x for x in self.S["postfill"] if x.get("night") == self.S.get("night")] + [dict(night=self.S.get("night"), sym=leg["sym"], entry=leg["entry"], bb=avg)]\n'),
  ('    def step(self, now, spot, ch, ind, stopped=False):\n        self.cfg = cfg()\n', RECORD),
  ('        if (hm >= 2330 or hm < 1715) and self.open_legs() and ind:\n            changed |= self._crash_guard(now, spot, ch, ind)\n        if changed:\n',
   '        if (hm >= 2330 or hm < 1715) and self.open_legs() and ind:\n            changed |= self._crash_guard(now, spot, ch, ind)\n'
   '        if self.S.get("night") and (hm >= 2330 or hm < 1730):\n            self._record(now, spot, ch)\n        if changed:\n'),
 ],
 "nightbot.py": [
  ('"v5aslp", "v5aslf", "v5aslh")]', '"v5aslp", "v5aslf", "v5aslh", "v5aslk", "v5asl15", "v5aslhk")]'),
 ],
 "control.py": [
  ('"v5aslf", "v5aslh", "nlive"', '"v5aslf", "v5aslh", "v5aslk", "v5asl15", "v5aslhk", "nlive"'),
 ],
 "ui.py": [
  ('    for v in ("v4a", "v5a", "v4asl", "v5asl", "v5aslj", "v5aslp", "v5aslf", "v5aslh", "nlive"):\n',
   '    for v in ("v4a", "v5a", "v4asl", "v5asl", "v5aslj", "v5aslp", "v5aslf", "v5aslh", "v5aslk", "v5asl15", "v5aslhk", "nlive"):\n'),
  ('    "v5aslh": ("BTC Night Leg V5A-CG-SL-H (any flag x1.5, no flag half)", ',
   '    "v5aslk": ("BTC Night Leg V5A-CG-SL-K (guard at sold strike, no flags)", "V5A-CG-SL with the crash guard at the sold strike instead of 2 x ATR, no size flags. The #2 fallback of the 19-Nov ranking. Paper only, added 20-Nov-2026."),\n'
   '    "v5asl15": ("BTC Night Leg V5A-CG-SL-G15 (guard 1.5 x ATR)", "V5A-CG-SL with the crash guard at 1.5 x ATR. Guard-level comparison with V5A-CG-SL (2 x ATR) and -K (at strike). Paper only, added 20-Nov-2026."),\n'
   '    "v5aslhk": ("BTC Night Leg V5A-CG-SL-HK (flags H + hedge-exists + guard at strike)", "Paper twin of the live rules: any flag x1.5 only if a far option is on offer (put <= 30 %, call <= 50 % of the bid), no flag x0.5, guard at the sold strike (paper holds no far options). Added 20-Nov-2026."),\n'
   '    "v5aslh": ("BTC Night Leg V5A-CG-SL-H (any flag x1.5, no flag half)", '),
 ],
}
def main():
    texts = {}
    for f, eds in EDITS.items():
        s = open(os.path.join(H, f), encoding="utf-8").read()
        if "v5aslhk" in s or "_record(self" in s or ("postfill" in s and f == "nightlive.py"):
            print("already applied: " + f); continue
        for old, new in eds:
            if s.count(old) != 1:
                raise SystemExit("ANCHOR PROBLEM in %s (%d matches): %r - NOTHING WRITTEN" % (f, s.count(old), old[:70]))
            s = s.replace(old, new)
        texts[f] = s
    for f, s in texts.items():
        shutil.copy(os.path.join(H, f), os.path.join(H, f + ".bak1120p"))
        open(os.path.join(H, f), "w", encoding="utf-8").write(s)
    print("PAPER PLUS PATCH DONE (%d files)" % len(texts))
if __name__ == "__main__":
    main()
