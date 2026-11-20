#!/usr/bin/env python3
"""topup_patch (20-Nov-2026, Sudip 11:15 "sell small base, buy hedge ... if all hedges are bought within 1 hr and other criteria
are fulfilled then sell bigger qty and hedges to follow as per old rule").
 - sizecalc: two figures per 0.01 base: 'safe' (no hedge, as now -> small base) and 'safe_big' (far option bought -> big base).
 - autosize 23:22: base = small base (as now); base_big = big base, written to state/night_live_cfg.json; limits follow base_big.
 - nightlive: 23:30 sale at the small base, far options as now. If EVERY sold option has its far option within 1 hour of the
   first sale and no insurance was bought, sell the extra up to the big base, once a night, per sold option, only if
   BTC is not past the strike and the strike is still >= half its first distance from BTC, and the bid is >= 80 % of the first
   sale price and >= the $10 floor. The extra's far options follow the old rule (bought after the sale, retry till 16:30,
   guard at the sold strike until covered). No double buying: each far option is tied to its own sale (cover id).
Every edit must match once, else NOTHING is written. Backups .bak1120t"""
import os, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
TOPUP = '''    def _topup(self, now, spot, ch, today):
        """20-Nov-2026: extra up to the big base once every far option of the first sale is bought within 1 hour (see topup_patch)"""
        S = self.S
        night = S.get("night")
        if not night or S.get("topup_night") == night:
            return False
        big, base = float(self.cfg.get("base_big") or 0), float(self.base)
        if big <= base + 1e-9:
            return False
        sold = [l for l in self.open_legs() if l["dir"] == "S" and l.get("kind") != "ins"]
        if not sold:
            return False
        t0 = min(dt.datetime.fromisoformat(l["t"]) for l in S["legs"] if l["dir"] == "S" and l.get("kind") != "ins")
        if any(l.get("kind") == "ins" for l in self.open_legs()):
            S["topup_night"] = night
            self.log("%s no top-up tonight: crash guard insurance bought" % self.lab)
            return True
        covered = all(sum(w["qty"] for w in S["legs"] if w.get("kind") == "wing" and w.get("cover") == l["id"] and not w["closed"]) >= l["qty"] - 1e-9 for l in sold)
        if not covered:
            if (now - t0).total_seconds() > 3600:
                S["topup_night"] = night
                self.log("%s no top-up tonight: far options not all bought within 1 hour" % self.lab)
                return True
            return False
        if (now - t0).total_seconds() > 3600:
            S["topup_night"] = night
            return True
        S["topup_night"] = night
        f = big / base - 1.0
        s0 = float(S.get("sale_spot") or spot)
        groups = {}
        for l in sold:
            groups.setdefault((l["set"], l["sym"]), []).append(l)
        notes = []
        for (key, sym), ls in groups.items():
            l = ls[0]
            q = sum(x["qty"] for x in ls)
            entry = sum(x["entry"] * x["qty"] for x in ls) / q
            extra = int(q * f / C + 1e-9) * C
            if extra < C - 1e-9:
                continue
            o = next((c for c in ch if c["sym"] == sym), None)
            if not o:
                notes.append("%s: not in the chain" % sym); continue
            past = (spot <= l["strike"]) if l["side"] == "PE" else (spot >= l["strike"])
            d0, d1 = abs(l["strike"] - s0), abs(l["strike"] - spot)
            if past or d1 < 0.5 * d0:
                notes.append("%s: BTC too close to the strike (%.0f now, %.0f at the sale)" % (sym, d1, d0)); continue
            if float(o.get("bid") or 0) < max(0.8 * entry, MIN_BID):
                notes.append("%s: bid %.1f below 80 %% of %.1f or the floor" % (sym, float(o.get("bid") or 0), entry)); continue
            leg = self._open(now, spot, key, l["kind"], l["side"], o, round(extra, 3), "S", "top-up to big base %.2f" % big)
            notes.append("%s: %s %.3f" % (sym, "sold extra" if leg else "extra not filled", extra))
        self.notify("%s TOP-UP to big base %.2f" % (self.lab, big), "; ".join(notes) or "nothing to add")
        return True

    def step(self, now, spot, ch, ind, stopped=False):
'''
EDITS = {
 "sizecalc.py": [
  ('    safe = max(cap + ins + mar, floor)                        # never below the floor\n',
   '    safe = max(cap + ins + mar, floor)                        # never below the floor\n'
   '    safe_big = max(n * wing + ins + mar, floor) if wing > 0 else safe   # 20-Nov-2026: after every far option is bought\n'),
  ('                safe=safe, hv14=hv14,', '                safe=safe, safe_big=safe_big, hv14=hv14,'),
 ],
 "autosize.py": [
  ('    safe = S["safe_floor_inr"] / S["usd_inr"]\n', '    safe = S["safe_floor_inr"] / S["usd_inr"]\n    safe_big = safe\n'),
  ('        safe = SC.safe_balance(spot, SC.tonight_ind(), S)["safe"]\n',
   '        _sb = SC.safe_balance(spot, SC.tonight_ind(), S)\n        safe, safe_big = _sb["safe"], _sb.get("safe_big", _sb["safe"])\n'),
  ('    return wallet, spot, open_pos, safe, S["usd_inr"], NW.tg_send\n', '    return wallet, spot, open_pos, safe, S["usd_inr"], NW.tg_send, safe_big\n'),
  ('        wallet, spot, open_pos, safe, fx, tg = read_all()\n', '        wallet, spot, open_pos, safe, fx, tg, safe_big = read_all()\n'),
  ('    D = decide(wallet, safe, live_base, armed, st, now)\n',
   '    D = decide(wallet, safe, live_base, armed, st, now)\n    big = max(0.0, min(floor001(wallet / safe_big * 0.01), D["max_base"]))\n'),
  ('    if st.get("ceiling") and now >= st.get("ceiling_from_ts", 0):\n        try:\n            lm = sync_limits(float(jload(CFG_F).get("base", live_base)))\n',
   '    if not open_pos:\n'
   '        cf = jload(CFG_F); bb = round(max(big, float(cf.get("base", live_base))), 2)\n'
   '        if abs(float(cf.get("base_big") or 0) - bb) > 1e-9:\n'
   '            cf["base_big"] = bb; jsave(CFG_F, cf)\n'
   '            msg = (msg + " | " if msg else "AUTO SIZE: ") + "big base (once every far option is bought) %.2f BTC, needs %s per 0.01" % (bb, rs(safe_big))\n'
   '    if st.get("ceiling") and now >= st.get("ceiling_from_ts", 0):\n        try:\n'
   '            _c = jload(CFG_F)\n            lm = sync_limits(float(_c.get("base_big") or _c.get("base", live_base)))\n'),
 ],
 "nightlive.py": [
  ('    def step(self, now, spot, ch, ind, stopped=False):\n', TOPUP),
  ('            first = first or leg\n            new_legs.append(leg)\n',
   '            first = first or leg\n            new_legs.append(leg)\n'
   '        if direction == "S" and new_legs and self.S.get("sale_spot_n") != self.S.get("night"):\n'
   '            self.S["sale_spot"], self.S["sale_spot_n"] = spot, self.S.get("night")\n'),
  ('        if 2330 <= hm <= 2358 and ind and not stopped and not self.S.get("halt"):\n            changed |= self._entries(now, spot, ch, ind, today)\n',
   '        if 2330 <= hm <= 2358 and ind and not stopped and not self.S.get("halt"):\n            changed |= self._entries(now, spot, ch, ind, today)\n'
   '        if (hm >= 2330 or hm < 130) and self.open_legs() and not stopped and not self.S.get("halt"):\n            changed |= self._topup(now, spot, ch, today)\n'),
 ],
}
def main():
    texts = {}
    for f, eds in EDITS.items():
        s = open(os.path.join(H, f), encoding="utf-8").read()
        if "safe_big" in s or "_topup(self" in s:
            print("already applied: " + f); continue
        for old, new in eds:
            if s.count(old) != 1:
                raise SystemExit("ANCHOR PROBLEM in %s (%d matches): %r - NOTHING WRITTEN" % (f, s.count(old), old[:70]))
            s = s.replace(old, new)
        texts[f] = s
    for f, s in texts.items():
        shutil.copy(os.path.join(H, f), os.path.join(H, f + ".bak1120t"))
        open(os.path.join(H, f), "w", encoding="utf-8").write(s)
    print("TOP-UP PATCH DONE (%d files)" % len(texts))
if __name__ == "__main__":
    main()
