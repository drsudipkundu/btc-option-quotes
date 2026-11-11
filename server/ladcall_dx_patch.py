"""11-Nov-2026 (Sudip): DECAY BUY-BACK for the ladder calls ("after the hunt is complete there is no point staying in the jungle").
For every sold call (covered, extra, extra part 2): once BTC has risen dx_arm (2 %) above the BTC price at that call's sale,
a resting buy-back sits at (1 - dx_level) x the sale price (97 % decay = 3 % of the sale price, rounded down to the 0.1 tick).
Not armed -> the call is held as before (lot-by-lot / stop / 17:20 / expiry all unchanged). After a decay buy-back nothing is
sold again until the next 17:35 (sold_day rule, unchanged).
Backtest basis: call-conditional-buyback-arm-x-test-2026-11-11 (extra 5 %: +153 vs hold per 1 BTC; covered +27; extra 6 % -78).
Only keys with dx_level > 0 use it (lv15). Editable any time in ~/deltabot/call_settings.json: {"lv15": {"dx_arm": 0.02, "dx_level": 0.97}}
(dx_level 0 = off, dx_arm 0 = order from the sale itself).
PAPER: strict - filled only when Delta's real best ask is at or below the limit, for the size shown there, paying the limit.
LIVE: nothing happens unless dx_live = 1 (default 0): then a real reduce-only resting limit buy; it is cancelled before any other
buy-back on that position and placed again for what is left. NOT yet tried on the real exchange.
Idempotent, backup ladcall.py.bak_dx. Apply AFTER ladcall_v15_patch.py."""
import os, sys, shutil
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(H, "ladcall.py"); s = open(p, encoding="utf-8").read()
if "def _dx(" in s:
    print("ladcall.py already has the decay buy-back"); sys.exit(0)
if "PARAMS_BY_KEY" not in s:
    raise SystemExit("ladcall.py has no v15 split yet (run ladcall_v15_patch.py first) - nothing written")
def rep(a, b):
    global s
    if s.count(a) != 1:
        raise SystemExit("ANCHOR PROBLEM (%d hits): %r - nothing written" % (s.count(a), a[:60]))
    s = s.replace(a, b)

rep('import os, json, csv, time, datetime as dt\n', 'import os, json, csv, time, math, datetime as dt\n')
rep('PARAMS_BY_KEY = {"lv15": dict(split_n=2, otm2=1.06, xmul=5.0, xmax_btc=0.3, x2_until=1755)}\n',
'''CP.update(dx_level=0.0, dx_arm=0.02, dx_live=0)   # decay buy-back: dx_level 0 = off (v9..v13 unchanged)
DX_TICK = 0.1
PARAMS_BY_KEY = {"lv15": dict(split_n=2, otm2=1.06, xmul=5.0, xmax_btc=0.3, x2_until=1755, dx_level=0.97, dx_arm=0.02)}
''')
rep('if k in ("xmul", "xmax_btc", "split_n", "otm2", "x2_until")})',
    'if k in ("xmul", "xmax_btc", "split_n", "otm2", "x2_until", "dx_arm", "dx_level", "dx_live")})')
rep('''        o = next((x for x in self._ch if x["sym"] == p["sym"]), None) or dict(sym=p["sym"], ask=0, mark=0, strike=p["k"])
        fills = self.ex.buy(o, int(n), cap)
''',
'''        self._dx_cancel(now, spot, p)
        n = min(int(n), p["c"])
        if n <= 0:
            self.S["pos"] = [x for x in self.S["pos"] if x["c"] > 0]
            return 0
        o = next((x for x in self._ch if x["sym"] == p["sym"]), None) or dict(sym=p["sym"], ask=0, mark=0, strike=p["k"])
        fills = self.ex.buy(o, int(n), cap)
''')
rep('''                        excess -= self._buy_back(now, mark, p, n, "LOT", P["bb_cap"]) or 0
                        changed = True
''',
'''                        excess -= self._buy_back(now, mark, p, n, "LOT", P["bb_cap"]) or 0
                        changed = True
                if P.get("dx_level"):
                    changed = self._dx(now, now_ts, mark, ch) or changed
''')
rep('S["pos"].append(dict(sym=a["sym"], k=a["k"], kind=kind, c=a["c"], entry=avg, fee=a["fee"], exp=J["exp"]))',
    'S["pos"].append(dict(sym=a["sym"], k=a["k"], kind=kind, c=a["c"], entry=avg, fee=a["fee"], exp=J["exp"], s0=spot))')
rep('    # ---------------------------------------------------------------- one tick\n',
'''    # ---------------------------------------------------------------- decay buy-back (11-Nov-2026)
    def _dx_limit(self, p):
        return max(DX_TICK, round(math.floor(p["entry"] * (1 - self.P["dx_level"]) / DX_TICK + 1e-9) * DX_TICK, 2))

    def _dx_apply(self, now, spot, p, q, px, fe):
        q = min(int(q), p["c"])
        if q <= 0:
            return 0
        f_out = fe if fe is not None else opt_fee(spot, px, q * C)
        f_in = p["fee"] * q / p["c"]
        pnl = (p["entry"] - px) * q * C - f_in - f_out
        p["fee"] -= f_in
        p["c"] -= q
        self.S["total_pnl"] += pnl
        self.row(now, "BUYBACK-DECAY", p["kind"], p["sym"], p["k"], q, px, f_out, pnl,
                 "sold @ %.1f; resting buy-back at %.0f %% decay" % (p["entry"], self.P["dx_level"] * 100))
        self.notify("%s call DECAY: bought back %d %s @ %.1f" % (self.key, q, p["sym"], px), "P&L %.2f USD" % pnl)
        return q

    def _dx_cancel(self, now, spot, p):
        """live: take the resting buy-back order away before any other buy on this position (books what it filled)."""
        oid = p.pop("dx_oid", None)
        done = p.pop("dx_of", 0)
        if not oid:
            return
        try:
            self.ex.cl.cancel(oid, p["sym"])
        except Exception:
            pass
        try:
            r = self.ex.cl.order(oid)
            if r["filled"] > done:
                self._dx_apply(now, spot, p, r["filled"] - done, r["avg"] or self._dx_limit(p), r["fee"] if not done else None)
        except Exception as e:
            self.log("%s decay order %s could not be read after cancel: %s" % (self.key, oid, e))

    def _dx_live(self, now, spot, p, lim):
        cl = self.ex.cl
        oid = p.get("dx_oid")
        if oid:
            try:
                r = cl.order(oid)
            except Exception as e:
                self.log("%s decay order %s could not be read: %s" % (self.key, oid, e))
                return False
            done, ch = p.get("dx_of", 0), False
            if r["filled"] > done:
                self._dx_apply(now, spot, p, r["filled"] - done, r["avg"] or lim, r["fee"] if not done else None)
                p["dx_of"], ch = r["filled"], True
            if r["state"] in ("cancelled", "rejected", "closed"):
                p.pop("dx_oid", None)
                p.pop("dx_of", None)
                ch = True
            return ch
        if p["c"] < 1 or time.time() - p.get("dx_try", 0) < 300:
            return False
        try:
            self.ex.check(p["sym"], "buy", int(p["c"]), True)
            r = cl.place(p["sym"], "buy", int(p["c"]), lim, True, "dx%d" % (int(time.time() * 10) % 10 ** 9))
            p["dx_oid"], p["dx_of"] = r["id"], 0
            self.row(now, "DECAY-ORDER", p["kind"], p["sym"], p["k"], p["c"], lim, 0, 0, "resting reduce-only buy placed")
        except Exception as e:
            p["dx_try"] = time.time()
            self.log("%s decay order not placed (%s) - tried again in 5 min" % (self.key, e))
        return True

    def _dx(self, now, now_ts, mark, ch):
        """arm when BTC is dx_arm above the price at the sale; then a resting buy-back at (1 - dx_level) x sale price."""
        P, changed = self.P, False
        used = self.__dict__.setdefault("_dx_used", {})
        for p in list(self.S["pos"]):
            s0 = p.get("s0")
            if not s0 or p["c"] <= 0:
                continue
            lim = self._dx_limit(p)
            if not p.get("dx_arm"):
                if mark < s0 * (1 + P["dx_arm"]):
                    continue
                p["dx_arm"], changed = now_ts, True
                self.row(now, "DECAY-ARMED", p["kind"], p["sym"], p["k"], p["c"], lim, 0, 0,
                         "BTC %.0f is %.1f %% above %.0f at the sale; resting buy-back at %.1f (sold @ %.1f)" % (
                             mark, (mark / s0 - 1) * 100, s0, lim, p["entry"]))
                self.log("%s call: decay buy-back armed %s x%d at %.1f" % (self.key, p["sym"], p["c"], lim))
            if self.mode != "paper":
                if P.get("dx_live") and hasattr(self.ex, "cl"):
                    changed = self._dx_live(now, mark, p, lim) or changed
                continue
            o = next((x for x in ch if x["sym"] == p["sym"]), None)
            if o and 0 < o["ask"] <= lim + 1e-9:
                q = p["c"]
                if hasattr(self.ex, "book"):
                    try:
                        _, asks = self.ex.book(p["sym"])
                        u = used.get(p["sym"], [0, 0])
                        took = u[0] if now_ts - u[1] < 180 else 0      # size already taken from this ask in the last 3 min
                        q = min(q, sum(int(z) for a, z in asks if a <= lim + 1e-9) - took)
                    except Exception:
                        q = 0
                if q > 0:
                    u = used.get(p["sym"], [0, 0])
                    used[p["sym"]] = [(u[0] if now_ts - u[1] < 180 else 0) + q, now_ts]
                    self._dx_apply(now, mark, p, q, lim, None)
                    changed = True
        self.S["pos"] = [x for x in self.S["pos"] if x["c"] > 0]
        return changed

    # ---------------------------------------------------------------- one tick
''')
shutil.copy2(p, p + ".bak_dx")
open(p, "w", encoding="utf-8").write(s)
print("ladcall.py: decay buy-back added (only lv15 uses it; live off until dx_live = 1)")
