"""offline self-test of qtycap_patch (per-night sold / bought totals tied to the base). No network, no key, throw-away folder.
Plays orders straight into the REAL live-seller class: under the cap passes, over the cap is refused, closing orders are never
counted or blocked, a new night starts from zero, the limits.json override works, buys are counted separately from sells."""
import os, sys, json, tempfile
CODE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
os.environ["BOT_HOME"] = tmp
sys.path.insert(0, CODE)
import guard, nightlive as LV
assert LV.HOME == tmp and guard.HOME == tmp, "test must not touch the real folders"
assert hasattr(LV.LiveNight, "_night_cap"), "patch not applied"


class Fake:
    def __init__(self):
        self.n, self.o = 1, {}

    def positions(self):
        return {}

    def place(self, s, side, size, price, reduce_only=False, cid=None):
        o = dict(id=self.n, state="closed", size=size, filled=size, avg=10.0, fee=0.01)
        self.o[self.n] = o
        self.n += 1
        return o

    def order(self, i):
        return self.o[i]

    def cancel(self, i, s):
        pass


def mk(base, night="2026-11-26"):
    json.dump(dict(armed=True, acct="test", base=base, client="paper"), open(LV.CFG_F, "w"))
    json.dump(dict(max_order_btc=5 * base, max_open_btc=100.0, daily_loss_usd=60), open(guard.LIMITS_F, "w"))
    n = LV.LiveNight(Fake(), base, lambda *a: None, lambda *a: None, sleep=lambda s: None)
    n.S["night"] = night
    return n


def refused(n, side, c, ro=False):
    try:
        n._order("P-BTC-80000-271126", side, c, 10.0, ro, 0)
        return False
    except guard.LimitBreach:
        return True


n = mk(0.06)    # night cap = 7 x 0.06 = 0.42 BTC = 420 contracts; per-order cap 0.30 = 300 contracts
assert not refused(n, "sell", 300), "first 300 should pass"
assert not refused(n, "sell", 100), "400 total should pass"
assert refused(n, "sell", 30), "430 total must be refused"
print("OK  sold total: 0.40 passes, 0.43 refused (cap 0.42 = 7 x base)")
assert not refused(n, "buy", 300, ro=True), "closing buy never blocked"
assert not refused(n, "buy", 300, ro=True), "closing buy again never blocked"
assert n.S["qcap"]["bought"] == 0.0, "closing orders must not be counted"
print("OK  closing (reduce-only) orders are never counted or blocked")
assert not refused(n, "buy", 300), "hedge buy 300 passes (own counter)"
assert not refused(n, "buy", 120), "420 bought passes"
assert refused(n, "buy", 1), "421 bought refused"
print("OK  bought total is counted separately from sold")
n.S["night"] = "2026-11-27"
assert not refused(n, "sell", 300), "new night starts from zero"
print("OK  a new night starts from zero")
json.dump(dict(max_order_btc=5.0, max_open_btc=100.0, daily_loss_usd=60, max_sold_night_btc=0.5), open(guard.LIMITS_F, "w"))
assert not refused(n, "sell", 150) and refused(n, "sell", 100), "override 0.5 BTC"
print("OK  limits.json override (max_sold_night_btc) works")
n2 = mk(0.20, "2026-11-28")    # base 0.20 -> cap 1.4 BTC, normal night 1.1
assert not refused(n2, "sell", 900) and not refused(n2, "sell", 200) and not refused(n2, "sell", 300), "1.4 BTC passes"
assert refused(n2, "sell", 100), "1.5 refused"
print("OK  base 0.20: normal night 1.1 passes, cap 1.4")
n3 = LV.LiveNight(Fake(), 0.20, lambda *a: None, lambda *a: None, sleep=lambda s: None)
assert n3.S.get("qcap", {}).get("sold") == n2.S["qcap"]["sold"], "totals must survive a restart (saved with the state)"
print("OK  totals are saved, so a restart cannot reset the night")
print("QTYCAP SELFTEST PASSED")
