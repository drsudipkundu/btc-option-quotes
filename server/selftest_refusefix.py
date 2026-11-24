"""offline self-test of refusefix_patch: Delta refuses (HTTP 400) the first strikes -> the bot must move on to the next strikes,
reduce-only orders must still raise, other errors must still raise, ONE message lists the refused strikes."""
import os, sys, types, tempfile, datetime as dt
CODE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
os.environ["BOT_HOME"] = tmp
sys.path.insert(0, CODE)
try:
    import nightlogic, guard                      # the real ones on the server
except ImportError:                               # sandbox without the server files: minimal stand-ins
    IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
    class Night:
        def __init__(self, *a, **k): self.notify = k.get("notify"); self.log = k.get("log") or (lambda *x: None)
        def load(self): pass
        def save(self): pass
    nl = types.ModuleType("nightlogic")
    nl.Night, nl.IST, nl.MIN_BID = Night, IST, 10.0
    nl.find = nl.fee = nl.next_expiry_ts = nl.indicators = lambda *a, **k: None
    nl.is_full = lambda o, full=(): bool(o.get("ro"))
    sys.modules["nightlogic"] = nl
    g = types.ModuleType("guard"); g.check_order = lambda *a, **k: None; sys.modules["guard"] = g
import nightlive as LV
assert LV.HOME == tmp, "test must not touch the real folders"
if not hasattr(LV.LiveNight, "_refused_note"):
    import refusefix_patch as RP
    RP.H = tmp
    import shutil; shutil.copy2(LV.__file__, tmp + "/nightlive.py")
    RP.main(); import importlib; sys.path.insert(0, tmp); LV = importlib.reload(importlib.import_module("nightlive")) if False else None
    import importlib.util
    sp = importlib.util.spec_from_file_location("nl_patched", tmp + "/nightlive.py"); LV = importlib.util.module_from_spec(sp); sp.loader.exec_module(LV)

def S(k): return "C-BTC-%d-251124" % k
REFUSED = {S(k) for k in (84000, 84200)}               # first two strikes at the open-interest cap

class Fake:
    def __init__(self): self.placed, self.pos = [], {}; self.nid = 1
    def ticker(self, s): return dict(bid=40.0, ask=44.0, mark=42.0, tick=0.5)
    def _http(self, m, p, q=None): return {"result": {"buy": [{"price": 40.0, "size": 10**6}], "sell": [{"price": 44.0, "size": 10**6}]}}
    def positions(self): return self.pos
    def place(self, s, side, size, price, ro=False, cid=None):
        if s == S(88888):
            raise RuntimeError("HTTP 400 some other rejection")
        if s in REFUSED and not ro:
            raise RuntimeError("HTTP 400 {'error': {'code': 'only_reduce_only_orders_allowed'}}")
        if s == S(99999):
            raise RuntimeError("connection reset")
        self.placed.append((s, side, size, ro)); self.nid += 1
        return dict(id=self.nid, state="closed", size=size, filled=size, unfilled=0, avg=price, fee=0.01)
    def order(self, i): return dict(id=i, state="closed", filled=1, avg=40.0, fee=0.01, size=1, unfilled=0)
    def cancel(self, *a): pass

msgs = []
ex = Fake()
n = LV.LiveNight(ex, 0.02, lambda s, b="": msgs.append((s, b)), lambda *a: None, sleep=lambda s: None, now_fn=lambda: dt.datetime(2026, 11, 24, 23, 31, tzinfo=LV.IST))
n.cfg.update(polite_s=0, retry_wait_s=0, fill_wait_s=0)
n.ch = [dict(sym=S(k), typ="CE", strike=float(k), exp=1, bid=40.0, ask=44.0, mark=42.0, ro=False) for k in range(84000, 85600, 200)]
n.S["exp"] = 1
o0 = n.ch[0]
fills = n.sell_smart(o0, 2, "CE")
sold = {f[0]["sym"] for f in fills}
assert fills and not (sold & REFUSED), "sold on a refused strike? %s" % sold
assert S(84400) in sold, "did not move on to the first open strike: %s" % sold
print("OK smart sell moved past the refused strikes ->", sorted(sold))
assert len([m for m in msgs if "REFUSED" in m[0]]) == 1, msgs
body = [m for m in msgs if "REFUSED" in m[0]][0][1]
assert S(84000) in body and S(84200) in body and "only_reduce_only" in body
print("OK ONE message lists both refused strikes")

try:
    n._order(S(88888), "buy", 1, 40.0, True, 0)       # reduce-only, HTTP 400 -> must still raise
    raise SystemExit("FAIL reduce-only error was swallowed")
except RuntimeError:
    print("OK reduce-only order errors still raise")
try:
    n._order(S(99999), "sell", 1, 40.0, False, 0)      # not an exchange refusal -> must still raise
    raise SystemExit("FAIL other errors were swallowed")
except RuntimeError:
    print("OK network/other errors still raise")
r = n._order(S(84000), "sell", 1, 40.0, False, 0)
assert r == (0, 0.0, 0.0)
print("OK a refused new order counts as 0 filled")
print("REFUSEFIX SELFTEST PASSED")
