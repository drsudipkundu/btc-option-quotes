"""offline self-test of the 02:30 top-up window (c31): runs the installed _topup on a pretend night (no orders, no exchange)"""
import os, sys, datetime as dt
CODE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(os.environ.get("TOPUP_SRC", CODE), "nightlive.py"), encoding="utf-8").read()
assert "_topup_deadline" in src, "patch not applied"
a = src.index("    def _topup(self, now, spot, ch, today):\n"); body = src[a:src.index("    def step(self, now, spot, ch, ind, stopped=False):\n", a)]
assert "def _topup_deadline" in body
ns = dict(dt=dt, C=0.001, MIN_BID=10.0)
exec("class T:\n" + body, ns)
T0 = dt.datetime(2026, 11, 27, 23, 31)
SYM = {"PE": "P-BTC-59000-281126", "CE": "C-BTC-64000-281126"}; K = {"PE": 59000.0, "CE": 64000.0}

def mk(hedged, cfg=None):
    t = ns["T"](); t.lab, t.base, t.cfg, t.msgs, t.opened = "T", 0.06, dict({"base_big": 0.09}, **(cfg or {})), [], []
    legs = []
    for i, sd in enumerate(("PE", "CE")):
        legs.append(dict(id=i + 1, dir="S", side=sd, kind="trend", set="s", sym=SYM[sd], strike=K[sd], qty=0.06, entry=100.0, t=T0.isoformat(), closed=False))
        if sd in hedged:
            legs.append(dict(id=10 + i, dir="B", side=sd, kind="wing", cover=i + 1, qty=0.06, closed=False, t=T0.isoformat()))
    t.S = dict(night="n1", legs=legs, sale_spot=61500.0)
    t.open_legs = lambda: [l for l in t.S["legs"] if not l["closed"]]
    t.log = lambda *a: None; t.notify = lambda s, b="": t.msgs.append(s + " | " + b)
    def _open(now, spot, key, kind, side, o, q, d, why):
        l = dict(id=50 + len(t.opened), dir="S", side=side, kind=kind, set=key, sym=o["sym"], strike=o["strike"], qty=q, entry=o["bid"], t=now.isoformat(), closed=False)
        t.S["legs"].append(l); t.opened.append((side, q)); return l
    t._open = _open
    return t
def hedge(t, sd):
    t.S["legs"].append(dict(id=77, dir="B", side=sd, kind="wing", cover=2 if sd == "CE" else 1, qty=0.06, closed=False, t=T0.isoformat()))
CH = [dict(sym=SYM[s], strike=K[s], bid=95.0) for s in SYM]
LOW = [dict(sym=SYM[s], strike=K[s], bid=60.0) for s in SYM]
run = lambda t, mins, ch=CH, spot=61500.0: t._topup(T0 + dt.timedelta(minutes=mins), spot, ch, None)

t = mk(set()); d = t._topup_deadline(T0)
assert d == dt.datetime(2026, 11, 28, 2, 30), d; print("OK window ends 02:30 next morning")
t = mk({"PE", "CE"}); run(t, 2); run(t, 3)
assert sorted(t.opened) == [("CE", 0.03), ("PE", 0.03)]; print("OK hedges at once -> both sides topped up once (unchanged)")
t = mk({"PE"}); run(t, 5); run(t, 70); hedge(t, "CE"); run(t, 99); run(t, 120)
assert sorted(t.opened) == [("CE", 0.03), ("PE", 0.03)], t.opened; print("OK call hedge 99 minutes late -> call side topped up (was refused under the 1-hour rule)")
t = mk({"PE"}); run(t, 5); hedge(t, "CE"); run(t, 178)
assert sorted(t.opened) == [("CE", 0.03), ("PE", 0.03)], t.opened; print("OK hedge at 02:29 -> still topped up")
t = mk({"PE"}); run(t, 5); run(t, 181); hedge(t, "CE"); run(t, 185); run(t, 300)
assert t.opened == [("PE", 0.03)] and t.S.get("topup_night") == "n1", (t.opened, t.S.get("topup_night")); print("OK hedge after 02:30 -> no top-up, night closed for top-ups")
t = mk({"PE"}); run(t, 5); hedge(t, "CE"); run(t, 150, LOW); run(t, 160)
assert t.opened == [("PE", 0.03)] and any("below 80" in m for m in t.msgs), (t.opened, t.msgs); print("OK late hedge but bid under 80 % of the sale price -> no extra, tried once only")
t = mk({"PE"}); run(t, 5); hedge(t, "CE"); run(t, 150, CH, 63200.0)
assert t.opened == [("PE", 0.03)] and any("too close" in m for m in t.msgs); print("OK late hedge but BTC too close to the call -> no extra")
t = mk({"PE"}, {"topup_until": "00:30"}); run(t, 5); run(t, 61); hedge(t, "CE"); run(t, 65)
assert t.opened == [("PE", 0.03)]; print("OK setting topup_until 00:30 restores the 1-hour behaviour")
assert '7 * max(float(self.cfg.get("base", 0.02)), float(self.cfg.get("base_big") or 0))' in src; print("OK night cap follows the bigger of base and big base")
print("TOPUP0230 SELFTEST PASSED")
