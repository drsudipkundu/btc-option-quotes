"""26-Nov-2026 c26 (Sudip 19:45): per-NIGHT quantity totals, tied to the base.
Already in the guard (state/limits.json, set by autosize from the base): max per order and max open at a time.
New here: max_sold_night_btc and max_bought_night_btc = running totals of orders that ADD risk (sells; insurance buys).
Default 7 x base (normal night sells 5.5 x base, so about 1.27 x headroom). Edit state/limits.json to override.
Closing (reduce-only) orders are never counted or blocked. Breach = order refused, Telegram alert, nothing else changes.
Usage: python3 qtycap_patch.py ~/deltabot"""
import sys, os
home = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(home, "nightlive.py")
s = open(p).read()
if "def _night_cap(" in s:
    print("night quantity caps already installed"); sys.exit(0)
A1 = "    def _order(self, sym, side, n, price, reduce_only, wait_s):"
A2 = '        if not reduce_only:\n            guard.check_order(sym, side, n * C, False, self.cl.positions())\n'
A3 = '        return o["filled"], o["avg"], o["fee"]\n'
for a in (A1, A2, A3):
    if s.count(a) != 1:
        print("ERROR: anchor not found exactly once - nothing changed:", a[:60]); sys.exit(1)
HELP = '''    def _night_cap(self, side, n_contracts, add=False):
        """running per-night totals of risk-adding orders (sell / non-reduce buy). add=False: check, add=True: record the fill"""
        import guard
        nt = self.S.get("night")
        q = self.S.get("qcap")
        if not q or q.get("night") != nt:
            q = self.S["qcap"] = dict(night=nt, sold=0.0, bought=0.0)
        key = "sold" if side == "sell" else "bought"
        if add:
            q[key] = round(q[key] + n_contracts * C, 6)
            self.save()
            return
        try:
            lim = json.load(open(os.path.join(HOME, "state", "limits.json")))
        except Exception:
            lim = {}
        dflt = round(max(0.15, 7 * float(self.cfg.get("base", 0.02))), 3)
        cap = float(lim.get("max_sold_night_btc" if side == "sell" else "max_bought_night_btc", dflt))
        if q[key] + n_contracts * C > cap + 1e-9:
            raise guard.LimitBreach("night total %s %.3f + this order %.3f BTC is above the %.3f BTC per-night limit (state/limits.json)"
                                    % (key, q[key], n_contracts * C, cap))

'''
s = s.replace(A1, HELP + A1, 1)
s = s.replace(A2, A2 + "            self._night_cap(side, n)\n", 1)
s = s.replace(A3, '        if not reduce_only and o["filled"]:\n            self._night_cap(side, o["filled"], True)\n' + A3, 1)
open(p + ".bak1126q", "w").write(open(p).read())
open(p, "w").write(s)
print("night quantity caps installed in nightlive.py")
