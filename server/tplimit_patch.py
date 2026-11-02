# 3-Nov-2026 (Sudip): the 90% buy-back becomes a RESTING LIMIT ORDER at 10% of the sale price.
# Paper copies (nightlogic.Night, used by nightbot v4a/v5a/v4asl/v5asl): from the moment of the sale, a paper buy order
# rests at tp = 10% of entry (rounded down to 0.1). It fills when a real seller offers at or below it (option ask <= tp),
# at the tp price - never more. Replaces the old "mark <= 10% -> buy at the ask" rule. Idempotent; backup .bak_tp.
import sys, os
HOME = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(HOME, "nightlogic.py")
s = open(p, encoding="utf-8").read()
if "def tp_price" in s:
    print("nightlogic already has the resting buy-back"); sys.exit(0)
old = '''        # 90% early buy-back (clock before 23:30)
        if hm < 2330:
            for l in self.open_legs():
                if l["dir"] == "S":
                    o = find(ch, l["side"], l["strike"])
                    if o and o["mark"] > 0 and o["mark"] <= 0.1 * l["entry"]:
                        self._close(now, spot, l, o, "90PCT")
'''
new = '''        # 90% buy-back = resting limit buy at 10% of the sale price (3-Nov-2026): fills when a seller offers <= tp
        for l in self.open_legs():
            if l["dir"] == "S":
                o = find(ch, l["side"], l["strike"])
                tp = tp_price(l["entry"], 0.1)
                if o and tp > 0 and 0 < o["ask"] <= tp:
                        self._close_at(now, spot, l, tp, "90PCT")
'''
a = "def make_picks("
for x in (old, a):
    if s.count(x) != 1:
        raise SystemExit("ANCHOR PROBLEM (%d): %r - nothing written" % (s.count(x), x[:50]))
s = s.replace(old, new)
s = s.replace(a, '''def tp_price(entry, frac, tick=0.1):
    """resting buy-back price: frac x sale price, rounded DOWN to the tick (never pay more than the target)"""
    return round(math.floor(entry * frac / tick + 1e-9) * tick, 4)

''' + a)
old2 = "    def _close(self, now, spot, leg, o, why):"
if s.count(old2) != 1:
    raise SystemExit("ANCHOR PROBLEM _close - nothing written")
s = s.replace(old2, '''    def _close_at(self, now, spot, leg, px, why):
        """paper close of a short leg at a given price (resting limit filled)"""
        f = fee(spot, px, leg["qty"]) if px else 0.0
        pnl = (leg["entry"] - px) * leg["qty"] - leg["fee"] - f
        leg["closed"], leg["exit"], leg["pnl"] = True, px, pnl
        self.S["total_pnl"] += pnl
        self.row(now, "EXIT-" + why, leg, px, f, pnl, "resting limit buy-back filled")
        return pnl

''' + old2)
if not os.path.exists(p + ".bak_tp"):
    os.replace(p, p + ".bak_tp")
open(p, "w", encoding="utf-8").write(s)
print("nightlogic resting buy-back applied")
