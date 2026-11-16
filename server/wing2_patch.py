#!/usr/bin/env python3
"""wing2_patch (16-Nov-2026, Sudip's five points). Run in ~/deltabot after wing_live_patch.
 1. nightlive.py: SMART BUY for the hedge. Per strike: (a) polite bid at the middle of bid and ask for wing_polite_s (30 s), first strike
    only; (b) buy from the offers at the asking price; (c) wait 5 s, pay up to half-way to the cap; (d) wait 5 s, pay up to the cap
    (wing_cap 1.3 x the ask). Never above wing_max (50 %) of the sold option's price. Then the further / nearer strikes as before.
 2. nightlive.py: when the sold option of a side is closed (10 % buy-back or exit), the far option of that side is SOLD if anybody bids
    for it (tried every 5 minutes, never below 80 % of its worth); with no bidder it stays and expires - there is nobody to sell it to.
 3. autosize.py: optional CEILING (`autosize.py --ceiling 0.12 [YYYY-MM-DD]`): from that date the 23:22 run sets the base straight to
    what the balance allows (balance / safe balance per 0.01), up to the ceiling - up as well as down, no 7-day wait.
    `--ceiling 0` = back to the old rule (cuts at once, raises +0.01 per 7 days up to the hand-armed base).
Every edit must match exactly once, otherwise NOTHING is written. Backups: <file>.bak1116w2"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

EDITS = {
 "nightlive.py": [
  ("wing_tries=3, ins_cap=2.0,", "wing_tries=3, wing_polite_s=30, wing_sell_every_s=300, ins_cap=2.0,"),
  ('''                    cap = tick_round(min(t["ask"] * P["wing_cap"], top), t["tick"] or 0.5, False)
                    for i in range(int(P["wing_tries"])):
                        f, a, fe = self._sweep(o["sym"], "buy", left, cap, False, P["fill_wait_s"])
                        if f:''',
   '''                    tk = t["tick"] or 0.5
                    steps = []
                    if not first_done and P.get("wing_polite_s", 0) > 0:      # smart buy (a): polite bid in the middle
                        mid = tick_round((t["bid"] + t["ask"]) / 2 if t["bid"] > 0 else t["ask"] * 0.6, tk, True)
                        if mid < t["ask"] - 1e-9:
                            steps.append(("polite", mid))
                    first_done = True
                    nt = max(1, int(P["wing_tries"]))
                    for j in range(nt):                                        # (b)-(d): asking price, then step by step up to the cap
                        m = 1.0 + (P["wing_cap"] - 1.0) * (j / float(nt - 1) if nt > 1 else 1.0)
                        steps.append(("take", tick_round(min(t["ask"] * m, top), tk, False)))
                    for i, (how, cap) in enumerate(steps):
                        if how == "polite":
                            f, a, fe = self._order(o["sym"], "buy", left, cap, False, P["wing_polite_s"])
                        else:
                            f, a, fe = self._sweep(o["sym"], "buy", left, cap, False, P["fill_wait_s"])
                        if f:'''),
  ('''                        if i < int(P["wing_tries"]) - 1:
                            self.sleep(5)''',
   '''                        if how == "take" and i < len(steps) - 1:
                            self.sleep(5)'''),
  ('''            left, cost, why = want, 0.0, ""
            try:''', '''            left, cost, why, first_done = want, 0.0, "", False
            try:'''),
  ('''    def _settle(self, now, spot):
        if not all(l.get("kind") == "wing" for l in self.open_legs()):''',
   '''    def _wing_release(self, now, spot):
        """the sold option of a side is closed -> sell its far option if anybody bids (every 5 min); no bidder -> it expires"""
        done = False
        for l in list(self.open_legs()):
            if l.get("kind") != "wing" or any(x["dir"] == "S" and x["side"] == l["side"] for x in self.open_legs()):
                continue
            if time.time() - l.get("rel_try", 0) < self.cfg.get("wing_sell_every_s", 300):
                continue
            l["rel_try"] = time.time()
            try:
                if self._close(now, spot, l, None, "HEDGE") is not None:
                    done = True
            except Exception as e:
                self.log("far option sale failed: %s" % e)
        return done

    def _settle(self, now, spot):
        if not all(l.get("kind") == "wing" for l in self.open_legs()):'''),
  ('''        changed |= self.tp_poll(now)
        if self.S["night"] and not self.open_legs()''', '''        changed |= self.tp_poll(now)
        if now.timestamp() < self.S["exp"] - 900:
            changed |= self._wing_release(now, spot)
        if self.S["night"] and not self.open_legs()'''),
  ('''            self._finish(now, "closed early (90% resting buy-back)")''', '''            self._finish(now, "closed early (resting buy-back at 10 pc%s)" % (", far options sold" if any(l.get("kind") == "wing" for l in self.S["legs"]) else ""))'''),
 ],
 "autosize.py": [
  ('''    allowed = min(floor001(balance_usd / safe_usd_per_001 * 0.01), max_base)
''', '''    ceil_on = bool(st.get("ceiling")) and now_ts >= st.get("ceiling_from_ts", 0)
    if ceil_on:
        max_base = float(st["ceiling"])           # 16-Nov-2026: Sudip's ceiling; the balance decides the base up to it
    allowed = min(floor001(balance_usd / safe_usd_per_001 * 0.01), max_base)
'''),
  ('''    elif live_base < max_base - 1e-9 and allowed > live_base + 1e-9 and now_ts - last_change >= STEP_DAYS * 86400:
        out.update(action="raise", base=round(min(allowed, live_base + STEP_UP), 2))''',
   '''    elif ceil_on and allowed > live_base + 1e-9:
        out.update(action="raise", base=round(allowed, 2))
    elif live_base < max_base - 1e-9 and allowed > live_base + 1e-9 and now_ts - last_change >= STEP_DAYS * 86400:
        out.update(action="raise", base=round(min(allowed, live_base + STEP_UP), 2))'''),
  ('''    if not st.get("on", True) and not show:''', '''    if "--ceiling" in sys.argv:
        a = sys.argv[sys.argv.index("--ceiling") + 1:]
        c = float(a[0])
        if not (c == 0 or 0.01 <= c <= 0.30):
            print("REFUSED: ceiling must be 0 (off) or 0.01 to 0.30 BTC"); return
        if c == 0:
            st.pop("ceiling", None); st.pop("ceiling_from_ts", None)
        else:
            d = dt.datetime.strptime(a[1], "%Y-%m-%d").replace(tzinfo=IST) if len(a) > 1 else dt.datetime.now(IST)
            st.update(ceiling=c, ceiling_from_ts=d.timestamp())
        jsave(ST_F, st)
        print("ceiling:", ("%.2f BTC from %s" % (c, dt.datetime.fromtimestamp(st["ceiling_from_ts"], IST).strftime("%d-%b %H:%M"))) if c else "off (old rule)"); return
    if not st.get("on", True) and not show:'''),
 ],
}


def main():
    out = {}
    for fn, eds in EDITS.items():
        p = os.path.join(H, fn)
        s = open(p).read()
        if "_wing_release" in s or "ceiling_from_ts" in s:
            print("%s: already patched" % fn); continue
        if fn == "nightlive.py" and "_buy_wings" not in s:
            print("STOP: wing_live_patch is not installed. NOTHING WRITTEN"); sys.exit(1)
        for old, new in eds:
            if s.count(old) != 1:
                print("STOP: %s - expected exactly one match, found %d, for:\n%s\nNOTHING WRITTEN" % (fn, s.count(old), old[:120])); sys.exit(1)
            s = s.replace(old, new)
        out[fn] = s
    for fn, s in out.items():
        p = os.path.join(H, fn)
        if not os.path.exists(p + ".bak1116w2"):
            shutil.copy2(p, p + ".bak1116w2")
        open(p + ".tmp", "w").write(s); os.replace(p + ".tmp", p)
        print("patched", fn)
    print("WING2 PATCH DONE")


if __name__ == "__main__":
    main()
