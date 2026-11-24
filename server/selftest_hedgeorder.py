"""offline self-test of the hedge order (c10): runs the installed _wing_cands on a pretend option list (no orders, no exchange)"""
import os, sys, re
CODE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(os.environ.get("HEDGE_SRC", CODE), "nightlive.py"), encoding="utf-8").read()
a = src.index("    def _wing_cands(self, leg, spot, w):\n"); b = src.index("    def _buy_wings(self, now, spot, sold):\n", a)
ns = {"is_full": lambda o, full: False}
exec("class T:\n" + src[a:b], ns)
ok = True
def chk(name, cond):
    global ok
    print(("OK   " if cond else "FAIL ") + name); ok = ok and cond
def mk(typ, strikes, cfg=None):
    t = ns["T"](); t.S = {"exp": 1, "full": []}; t.cfg = cfg or {"further": 4}
    t.ch = [dict(typ=typ, strike=float(k), exp=1, sym="%s-%d" % (typ, k)) for k in strikes]
    return t
ks = [x for x in (list(range(62000, 67001, 200)))]
# call: sold 62400, BTC 60000, wing 4 % -> target >= 64800
t = mk("CE", ks); o = [c["strike"] for c in t._wing_cands(dict(side="CE", strike=62400.0), 60000.0, 0.04)]
chk("call order: target, 1 in, 1 out, 2 in, 2 out ...  %s" % o[:7], o[:7] == [64800, 64600, 65000, 64400, 65200, 64200, 65400])
chk("call: no strike twice, nothing inside the sold strike", len(o) == len(set(o)) and min(o) > 62400)
# put: sold 57600, BTC 60000 -> target <= 55200
ks2 = list(range(52000, 58001, 200))
t = mk("PE", ks2); o = [c["strike"] for c in t._wing_cands(dict(side="PE", strike=57600.0), 60000.0, 0.04)]
chk("put order: target, 1 in, 1 out, 2 in, 2 out ...  %s" % o[:7], o[:7] == [55200, 55400, 55000, 55600, 54800, 55800, 54600])
# strike list ends (tonight's put): list stops at 57200, sold 57600 -> only 'in' strikes exist (none beyond 57200)
t = mk("PE", [57200, 57400, 57600, 58000, 59000]); o = [c["strike"] for c in t._wing_cands(dict(side="PE", strike=57600.0), 60118.0, 0.04)]
chk("list ends: only the in-strikes, nearest to the target first  %s" % o, o == [57200, 57400])
# nothing in between: all out
t = mk("CE", [62400, 64800, 65000, 65200]); o = [c["strike"] for c in t._wing_cands(dict(side="CE", strike=62400.0), 60000.0, 0.04)]
chk("no in-strikes: target then out  %s" % o, o == [64800, 65000, 65200])
# nothing listed at all
t = mk("CE", [62400, 62600]); o = [c["strike"] for c in t._wing_cands(dict(side="CE", strike=62400.0), 60000.0, 0.04)]
chk("only a strike inside: used as 'in'  %s" % o, o == [62600])
t = mk("CE", [62400]); chk("nothing beyond the sold strike: empty list", t._wing_cands(dict(side="CE", strike=62400.0), 60000.0, 0.04) == [])
# 'further' limit still holds (4 -> at most 5 in + 5 out)
t = mk("CE", list(range(62000, 70001, 200)), {"further": 2}); o = t._wing_cands(dict(side="CE", strike=62400.0), 60000.0, 0.04)
chk("further=2: at most 3 in + 3 out = 6 strikes (got %d)" % len(o), len(o) == 6)
print("PASSED" if ok else "FAILED"); sys.exit(0 if ok else 1)
