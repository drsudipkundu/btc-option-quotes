"""offline self-test of the side-by-side top-up: runs the installed _topup on a small pretend night (no orders, no exchange)"""
import os, sys, re, datetime as dt
CODE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(os.environ.get("TOPUP_SRC", CODE), "nightlive.py"), encoding="utf-8").read()
if "topup_sides" not in src:
    sys.path.insert(0, CODE); import topupside_patch as TP; body = TP.NEW
else:
    a = src.index("    def _topup(self, now, spot, ch, today):\n"); body = src[a:src.index("    def step(self, now, spot, ch, ind, stopped=False):\n", a)]
ns = dict(dt=dt, C=0.001, MIN_BID=10.0)
exec("class T:\n" + body, ns)
T0 = dt.datetime(2026, 11, 24, 23, 31)
SYM = {"PE": "P-BTC-59000-251126", "CE": "C-BTC-64000-251126"}; K = {"PE": 59000.0, "CE": 64000.0}

def mk(hedged, ins=False):
    t = ns["T"](); t.lab, t.base, t.cfg, t.msgs, t.opened = "T", 0.06, {"base_big": 0.09}, [], []
    legs = []
    for i, sd in enumerate(("PE", "CE")):
        legs.append(dict(id=i + 1, dir="S", side=sd, kind="trend", set="s", sym=SYM[sd], strike=K[sd], qty=0.06, entry=100.0, t=T0.isoformat(), closed=False))
        if sd in hedged:
            legs.append(dict(id=10 + i, dir="B", side=sd, kind="wing", cover=i + 1, qty=0.06, closed=False, t=T0.isoformat()))
    if ins:
        legs.append(dict(id=99, dir="B", side="PE", kind="ins", qty=0.06, closed=False, t=T0.isoformat()))
    t.S = dict(night="n1", legs=legs, sale_spot=61500.0)
    t.open_legs = lambda: [l for l in t.S["legs"] if not l["closed"]]
    t.log = lambda *a: None; t.notify = lambda s, b="": t.msgs.append(s + " | " + b)
    def _open(now, spot, key, kind, side, o, q, d, why):
        l = dict(id=50 + len(t.opened), dir="S", side=side, kind=kind, set=key, sym=o["sym"], strike=o["strike"], qty=q, entry=o["bid"], t=now.isoformat(), closed=False)
        t.S["legs"].append(l); t.opened.append((side, q)); return l
    t._open = _open
    return t
CH = [dict(sym=SYM[s], strike=K[s], bid=95.0) for s in SYM]
run = lambda t, mins: t._topup(T0 + dt.timedelta(minutes=mins), 61500.0, CH, None)

t = mk({"PE", "CE"}); run(t, 5); run(t, 6)
assert sorted(t.opened) == [("CE", 0.03), ("PE", 0.03)], t.opened; print("OK both hedged -> both sides topped up once")
t = mk({"PE"}); run(t, 5); run(t, 20)
assert t.opened == [("PE", 0.03)], t.opened; print("OK put hedged, call hedge missing -> put side topped up alone")
t.S["legs"].append(dict(id=77, dir="B", side="CE", kind="wing", cover=2, qty=0.06, closed=False, t=T0.isoformat())); run(t, 40)
assert sorted(t.opened) == [("CE", 0.03), ("PE", 0.03)], t.opened; print("OK call hedge arrives at 40 min -> call side topped up then")
t = mk({"PE"}); run(t, 5); run(t, 70)
t.S["legs"].append(dict(id=77, dir="B", side="CE", kind="wing", cover=2, qty=0.06, closed=False, t=T0.isoformat())); run(t, 99)
assert t.opened == [("PE", 0.03)] and t.S.get("topup_night") == "n1", (t.opened, t.S.get("topup_night")); print("OK call hedge after 1 hour -> no call top-up")
t = mk(set()); run(t, 5); run(t, 70); run(t, 80)
assert t.opened == [] and t.S.get("topup_night") == "n1"; print("OK no hedge on either side -> no top-up")
t = mk({"PE", "CE"}, ins=True); run(t, 5)
assert t.opened == [] and t.S.get("topup_night") == "n1"; print("OK insurance bought -> no top-up on either side")
t = mk({"PE", "CE"}); t._topup(T0 + dt.timedelta(minutes=5), 59400.0, CH, None)
assert t.opened == [("CE", 0.03)] and any("too close" in m for m in t.msgs), (t.opened, t.msgs); print("OK BTC too close to the put -> only the call side topped up")
print("TOPUPSIDE SELFTEST PASSED")
