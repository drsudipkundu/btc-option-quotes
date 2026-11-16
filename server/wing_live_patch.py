#!/usr/bin/env python3
"""wing_live_patch (16-Nov-2026). Run in ~/deltabot. ALWAYS-ON HEDGE for the live night seller, behind one setting.
Behaviour-neutral until state/night_live_cfg.json gets wing > 0  (`nightlive.py --wing 4` = 4 %, `--wing 0` = off).

With wing on, right after every real sale (trend, boost, opposite leg) the seller BUYS the same quantity of the same-type option whose
strike is `wing` x BTC price beyond the sold strike (call: lowest listed strike at or above, put: highest at or below - the same choice
as the paper tracker wingpaper.py). Rules of the purchase:
  * pays at most wing_cap (1.3) x the ask, and never more than wing_max (50 %) of the price the sold option fetched;
  * no offer at that strike -> up to 4 strikes further out, then the strikes between (nearest to the target first);
  * whatever cannot be bought is reported; the 2-ATR crash guard still covers that uncovered part (it works on sold minus bought).
The far option is kept to the end: sold at the 17:20 exit only after the sold option of that side is closed, and never below 80 % of
its worth at the BTC price of that moment; otherwise Delta settles it at 17:30. If the sold option is bought back early (10 % resting
order) the far option simply stays and expires.
Also: after 17:30 the position check no longer compares (Delta has settled; the record is settled a few minutes later).
Paper copies, shadow fleets and every data collection are untouched.
Every edit must match exactly once, otherwise NOTHING is written. Backups: <file>.bak1116w"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

WING = '''    # ------------------------------------------------ always-on hedge: far option bought at the sale (16-Nov-2026)
    def _wing_cands(self, leg, spot, w):
        exp = self.S.get("exp")
        same = [o for o in (self.ch or []) if o["typ"] == leg["side"] and (not exp or o["exp"] == exp)]
        k, n = leg["strike"], int(self.cfg.get("further", 4))
        if leg["side"] == "CE":
            far = sorted([o for o in same if o["strike"] >= k + w * spot - 1e-9], key=lambda o: o["strike"])
            near = sorted([o for o in same if k < o["strike"] < k + w * spot - 1e-9], key=lambda o: -o["strike"])
        else:
            far = sorted([o for o in same if o["strike"] <= k - w * spot + 1e-9], key=lambda o: -o["strike"])
            near = sorted([o for o in same if k > o["strike"] > k - w * spot + 1e-9], key=lambda o: o["strike"])
        return far[:n + 1] + near[:n + 1]

    def _buy_wings(self, now, spot, sold):
        P = self.cfg
        w = float(P.get("wing") or 0)
        if w <= 0 or not sold:
            return
        import guard
        for s in sold:
            want = int(round(s["qty"] / C))
            left, cost, why = want, 0.0, ""
            try:
                for o in self._wing_cands(s, spot, w):
                    if left <= 0:
                        break
                    t = self.cl.ticker(o["sym"])
                    if t["ask"] <= 0:
                        continue
                    top = P["wing_max"] * s["entry"]
                    if t["ask"] > top:
                        why = "too costly (ask %.1f against a ceiling of %.1f)" % (t["ask"], top)
                        continue
                    cap = tick_round(min(t["ask"] * P["wing_cap"], top), t["tick"] or 0.5, False)
                    for i in range(int(P["wing_tries"])):
                        f, a, fe = self._sweep(o["sym"], "buy", left, cap, False, P["fill_wait_s"])
                        if f:
                            leg = dict(id=self.S["next_id"], set="wing", kind="wing", side=s["side"], sym=o["sym"], strike=o["strike"],
                                       qty=round(f * C, 3), dir="B", entry=a, t=now.isoformat(), closed=False, exit=None, fee=fe, cover=s["id"])
                            self.S["next_id"] += 1
                            self.S["legs"].append(leg)
                            self.save()
                            left -= f
                            cost += a * f * C + fe
                            self.row(now, "BUY", leg, a, fe, 0.0, "hedge: far option for %s" % s["sym"])
                            self.notify("%s HEDGE BOUGHT %s %d contracts @ %.1f" % (self.lab, o["sym"], f, a),
                                        "far option for %s (sold @ %.1f); strike %.0f is %.1f %% of BTC beyond the sold strike" % (
                                            s["sym"], s["entry"], o["strike"], abs(o["strike"] - s["strike"]) / spot * 100))
                        if left <= 0:
                            break
                        if i < int(P["wing_tries"]) - 1:
                            self.sleep(5)
            except guard.LimitBreach as e:
                why = "size limit: %s" % e
            except Exception as e:
                why = "order error: %s" % e
            prem = s["entry"] * s["qty"]
            if left > 0:
                self.notify("%s HEDGE NOT COMPLETE for %s: bought %d of %d contracts" % (self.lab, s["sym"], want - left, want),
                            "%s\\nThe crash guard (2 x ATR) still covers the uncovered part." % (why or "no offers at the far strikes"))
            elif prem > 0:
                self.log("%s hedge for %s cost %.2f USD = %.1f %% of the premium %.2f" % (self.lab, s["sym"], cost, cost / prem * 100, prem))
        self.save()

    def _settle(self, now, spot):
        if not all(l.get("kind") == "wing" for l in self.open_legs()):
            return Night._settle(self, now, spot)
        for l in self.open_legs():                         # only far options left: they expired at 17:30
            intr = max(0.0, l["strike"] - spot) if l["side"] == "PE" else max(0.0, spot - l["strike"])
            pnl = (intr - l["entry"]) * l["qty"] - l["fee"]
            l["closed"], l["exit"], l["pnl"] = True, intr, pnl
            self.S["total_pnl"] += pnl
            self.row(now, "SETTLE-WING", l, intr, 0.0, pnl, "far option expired at 17:30")
        self._finish(now, "far option expired at 17:30")

'''

EDITS = {
 "nightlive.py": [
  ("further=4, ins_cap=2.0,", "further=4, wing=0.0, wing_cap=1.3, wing_max=0.5, wing_tries=3, ins_cap=2.0,"),
  ('''        try:
            diffs = guard.reconcile(self.real_positions(), guard.expected_positions([self]))''',
   '''        if self.S.get("exp") and self.open_legs() and self.now_fn().timestamp() >= self.S["exp"]:
            return True                        # after 17:30 Delta has settled the options; the record follows a few minutes later
        try:
            diffs = guard.reconcile(self.real_positions(), guard.expected_positions([self]))'''),
  ('''    # ------------------------------------------------ Night hooks
''', WING + '''    # ------------------------------------------------ Night hooks
'''),
  ('''            for leg in new_legs:
                self._tp_place(leg)
''', '''            for leg in new_legs:
                self._tp_place(leg)
            if kind != "ins":
                self._buy_wings(now, spot, new_legs)
'''),
  ('''        if leg.get("tp_oid"):
            self._tp_cancel(now, leg)
            if leg["closed"]:
                return leg.get("pnl")
        n = int(round(leg["qty"] / C))''',
   '''        if leg.get("kind") == "wing" and any(l["dir"] == "S" and l["side"] == leg["side"] for l in self.open_legs()):
            return None                        # the far option is kept while the sold option of that side is open
        if leg.get("tp_oid"):
            self._tp_cancel(now, leg)
            if leg["closed"]:
                return leg.get("pnl")
        n = int(round(leg["qty"] / C))'''),
  ('''            f, avg, fe = self._sweep(leg["sym"], "sell", n, t["tick"] or 0.5, True, self.cfg["fill_wait_s"])''',
   '''            floor = t["tick"] or 0.5
            if leg.get("kind") == "wing":      # never below 80 % of its worth at this BTC price; otherwise Delta settles it at 17:30
                intr = max(0.0, leg["strike"] - spot) if leg["side"] == "PE" else max(0.0, spot - leg["strike"])
                floor = max(floor, tick_round(0.8 * intr, floor, True))
            f, avg, fe = self._sweep(leg["sym"], "sell", n, floor, True, self.cfg["fill_wait_s"])'''),
  ('''    ap.add_argument("--rule", choices=("v4asl", "v5asl"))
''', '''    ap.add_argument("--rule", choices=("v4asl", "v5asl"))
    ap.add_argument("--wing", type=float, metavar="PCT", help="always-on hedge: far option PCT %% beyond every sold strike; 0 = off")
'''),
  ('''    if a.arm:
        v = put_cfg(armed=True''', '''    if a.wing is not None:
        if not (a.wing == 0 or 1 <= a.wing <= 15):
            print("REFUSED: give 0 (off) or a percent between 1 and 15"); return
        print("hedge:", put_cfg(wing=round(a.wing / 100.0, 4)), "(used from the next sale; no restart needed)"); return
    if a.arm:
        v = put_cfg(armed=True'''),
  ('''armed %s, rules %s" % (c0["acct"], c0["base"], c0["client"], c0["armed"], c0.get("rule", "v4asl")))''',
   '''armed %s, rules %s, hedge %s" % (c0["acct"], c0["base"], c0["client"], c0["armed"], c0.get("rule", "v4asl"),
                                                       ("far option %.1f %% beyond every sale" % (c0["wing"] * 100)) if c0.get("wing") else "off"))'''),
 ],
 "nightbot.py": [
  ('''    exp = {}
    for l in S.get("legs", []):
        if l.get("closed"):
            continue''', '''    exp = {}
    if S.get("exp") and __import__("time").time() >= S["exp"]:
        S = dict(S, legs=[])                   # after 17:30 Delta has settled the options
    for l in S.get("legs", []):
        if l.get("closed"):
            continue'''),
 ],
}


def main():
    out = {}
    for fn, eds in EDITS.items():
        p = os.path.join(H, fn)
        s = open(p).read()
        if "_buy_wings" in s or "after 17:30 Delta has settled the options" in s and fn == "nightbot.py":
            print("%s: already patched" % fn)
            continue
        for old, new in eds:
            if s.count(old) != 1:
                print("STOP: %s - expected exactly one match, found %d, for:\n%s\nNOTHING WRITTEN" % (fn, s.count(old), old[:120]))
                sys.exit(1)
            s = s.replace(old, new)
        out[fn] = s
    for fn, s in out.items():
        p = os.path.join(H, fn)
        if not os.path.exists(p + ".bak1116w"):
            shutil.copy2(p, p + ".bak1116w")
        open(p + ".tmp", "w").write(s)
        os.replace(p + ".tmp", p)
        print("patched", fn)
    print("WING PATCH DONE (hedge stays OFF until: venv/bin/python nightlive.py --wing 4)")


if __name__ == "__main__":
    main()
