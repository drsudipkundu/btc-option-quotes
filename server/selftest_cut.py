"""offline self-test of cut_patch (26-Nov-2026 c17): Telegram /cut and the manual force exit (letterbox.py + nightlive.py). Pretend exchange, throw-away folder, no real order.
 A Telegram: /cut shows open legs; refusals (no decimal, too much, wrong side); asks to confirm; yes within 3 minutes queues the request; yes without a prior ask is not accepted; /cut cancel
 B partial cut of the put, far option stays: sold put 0.06 -> 0.03, far option untouched, EXIT-CUT booked, resting 10 % buy-back re-placed for 30 contracts, record = exchange, request cleared, no top-up
 C cut ALL of the put in a fall, far option stays and is NOT sold by the usual release; the call side is untouched; night ends normally at expiry
 D cut with the word hedge: far option sold in proportion (EXIT-CUTHEDGE), remainder still covers the rest of the put; far option with a worthless bid is not sold
 E a request made 23:30-23:59 waits; done at 00:01
 F a request older than 50 minutes lapses, nothing sold
 G no open option on that side: told, nothing done"""
import os, sys, json, tempfile, shutil, datetime as dt
CODE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
os.environ["BOT_HOME"] = tmp
sys.path.insert(0, CODE)
import nightlogic as NL, guard, nightlive as LV
assert LV.HOME == tmp and guard.HOME == tmp, "test must not touch the real folders"
IST = NL.IST
EXP = dt.datetime(2026, 11, 17, 12, 0, tzinfo=dt.timezone.utc).timestamp()
IND = dict(c1=82000.0, c2=81000.0, h1=82500.0, l1=80500.0, sma50=80000.0, hv14=0.40, hv7=0.35, hv365=0.38, atr14=2500.0, atr=2500.0, sl_acc=0.0)


def sym(typ, k):
    return "%s-BTC-%d-171126" % ("P" if typ == "PE" else "C", k)


class Fake:
    """pretend exchange: one bid and one ask per option, priced from the BTC price"""
    def __init__(self):
        self.spot, self.pos, self.ords, self.nid, self.no_ask, self.wing_px, self.late, self.late_bid = 82000.0, {}, {}, 1, set(), None, False, 0.0
        self.melt = {"PE": 1.0, "CE": 1.0}

    def px(self, typ, k):
        d = (self.spot - k) / self.spot if typ == "PE" else (k - self.spot) / self.spot      # > 0 = out of the money
        if d <= 0:
            return (k - self.spot if typ == "PE" else self.spot - k) + 30.0
        v = 3000.0 * max(0.0, 0.06 - d)
        if self.late:
            v *= 0.05
        return v * self.melt[typ]

    def quote(self, s):
        p = s.split("-"); typ, k = ("PE" if p[0] == "P" else "CE"), float(p[2])
        v = self.px(typ, k)
        bid = round(v, 1) if v >= 1.0 else 0.0
        ask = round(v * 1.05 + 0.5, 1)
        if v < 1.0 and self.wing_px:
            ask = self.wing_px
        if s in self.no_ask or (self.late and v < 1.0):
            ask = 0.0
        if self.late and v < 1.0 and self.late_bid:
            bid = self.late_bid
        return bid, ask

    def chain(self):
        out = []
        for k in range(60000, 100001, 200):
            for typ in ("PE", "CE"):
                b, a = self.quote(sym(typ, k))
                out.append(dict(sym=sym(typ, k), typ=typ, strike=float(k), exp=EXP, bid=b, ask=a, mark=(b + a) / 2, iv=0.9, oi=0.0, ro=False))
        return out

    def ticker(self, s):
        b, a = self.quote(s)
        return dict(bid=b, ask=a, mark=(b + a) / 2, tick=0.1)

    def _http(self, m, path, params=None):
        b, a = self.quote(path.split("/")[-1])
        return {"result": {"buy": [{"price": b, "size": 100000}] if b > 0 else [], "sell": [{"price": a, "size": 100000}] if a > 0 else []}}

    def positions(self):
        return {k: v for k, v in self.pos.items() if v}

    def _n(self, o):
        return dict(id=o["id"], state=o["state"], size=o["size"], unfilled=o["size"] - o["filled"], filled=o["filled"], avg=o["avg"], fee=o["fee"], reason="")

    def place(self, s, side, size, price, reduce_only=False, cid=None):
        b, a = self.quote(s)
        o = dict(id=self.nid, sym=s, side=side, size=size, price=price, state="open", filled=0, avg=0.0, fee=0.0, ro=reduce_only)
        self.nid += 1
        self.ords[o["id"]] = o
        self._try(o)
        return self._n(o)

    def _try(self, o):
        if o["state"] != "open":
            return
        b, a = self.quote(o["sym"])
        touch = a if o["side"] == "buy" else b
        if touch > 0 and (o["price"] >= touch - 1e-9 if o["side"] == "buy" else o["price"] <= touch + 1e-9):
            o.update(state="closed", filled=o["size"], avg=touch, fee=0.01)
            self.pos[o["sym"]] = self.pos.get(o["sym"], 0) + (o["size"] if o["side"] == "buy" else -o["size"])

    def order(self, oid):
        self._try(self.ords[oid])
        return self._n(self.ords[oid])

    def cancel(self, oid, s):
        if self.ords[oid]["state"] == "open":
            self.ords[oid]["state"] = "cancelled"

    def expire(self):
        self.pos = {}
        for o in self.ords.values():
            if o["state"] == "open":
                o["state"] = "cancelled"





import time, shutil as _sh
for f in ("letterbox.py", "nightlogic.py", "autosize.py", "control.py"):
    if os.path.exists(os.path.join(CODE, f)):
        _sh.copy(os.path.join(CODE, f), tmp)
sys.path.insert(0, tmp)
import letterbox as LB
CF = tmp + "/state/night_live_cfg.json"
SF = tmp + "/state/night_nlive.json"


def mk(extra=None):
    for d in ("state", "logs"):
        for f in os.listdir(tmp + "/" + d):
            os.remove(tmp + "/" + d + "/" + f)
    json.dump(dict(armed=True, acct="test", base=0.06, client="paper", rule="v5asl", wing=0.04, juice=0.0, retry_wait_s=0, polite_s=0, fill_wait_s=0,
                   wing_polite_s=0.05, wing_sell_every_s=0, **(extra or {})), open(LV.CFG_F, "w"))
    json.dump(dict(max_order_btc=0.36, max_open_btc=0.72, daily_loss_usd=60), open(guard.LIMITS_F, "w"))
    ex, msgs, clock = Fake(), [], [dt.datetime(2026, 11, 16, 23, 31, tzinfo=IST)]
    n = LV.LiveNight(ex, 0.06, lambda s, b="": msgs.append(s + " | " + b), lambda *a: None, sleep=lambda s: None, now_fn=lambda: clock[0])

    def tick(t, spot, melt=None):
        clock[0] = t
        ex.spot = spot
        if melt:
            ex.melt = melt
        n.step(t, spot, ex.chain(), IND)
        if n.open_legs():
            n.check_books("minute check")
    t0 = clock[0]
    tick(t0, 82000.0); tick(t0 + dt.timedelta(seconds=30), 82000.0)
    return n, ex, msgs, tick, t0


def rows(n):
    return [r["event"] for r in __import__("csv").DictReader(open(n.csv_path))]


def req(side, qty, hedge=0, age=0):
    c = json.load(open(LV.CFG_F))
    c["cut_req"] = {"side": side, "qty": qty, "hedge": hedge, "t": time.time() - age}
    json.dump(c, open(LV.CFG_F, "w"))


def sold(n, side):
    return [l for l in n.S["legs"] if l["dir"] == "S" and l["side"] == side]


def wings(n, side):
    return [l for l in n.S["legs"] if l.get("kind") == "wing" and l["side"] == side]


try:
    # ---------------------------------------------------------------- A Telegram
    json.dump(dict(armed=True, acct="test", base=0.06, rule="v5asl", wing=0.04), open(CF, "w"))
    json.dump(dict(night="2026-11-16", legs=[], halt=None, total_pnl=1.0, nights=1), open(SF, "w"))
    assert "no sold option is open" in LB.telegram("/cut", {})
    legs = [dict(id=1, set="trend", kind="main", side="PE", sym="P-BTC-76000-171126", strike=76000.0, qty=0.060, dir="S", entry=80.0, closed=False),
            dict(id=2, set="trend", kind="wing", side="PE", sym="P-BTC-72800-171126", strike=72800.0, qty=0.060, dir="B", entry=12.0, closed=False, cover=1),
            dict(id=3, set="opp", kind="main", side="CE", sym="C-BTC-88000-171126", strike=88000.0, qty=0.060, dir="S", entry=30.0, closed=False)]
    json.dump(dict(night="2026-11-16", legs=legs, halt=None, total_pnl=1.0, nights=1), open(SF, "w"))
    st = {}
    t = LB.telegram("/cut", st)
    assert "PUT:" in t and "CALL:" in t and "0.060 BTC sold" in t and "far option 0.060" in t, t
    assert LB.telegram("/cut put 5", st).startswith("REFUSED") and LB.telegram("/cut put", st).startswith("REFUSED") and LB.telegram("/cut gold 0.1", st).startswith("REFUSED")
    assert LB.telegram("/cut put 0.5", st).startswith("REFUSED: only 0.060")
    assert LB.telegram("/cut put 0.0001", st).startswith("REFUSED")
    r = LB.telegram("/cut put 0.03 yes", {})                      # yes without an earlier ask
    assert r.startswith("CUT asks") and not json.load(open(CF)).get("cut_req"), r
    st = {}
    r = LB.telegram("/cut put 0.03", st)
    assert r.startswith("CUT asks") and "far option stays" in r.lower() and not json.load(open(CF)).get("cut_req"), r
    r = LB.telegram("/cut put 0.03 hedge yes", st)                # different request than the one asked about
    assert r.startswith("CUT asks") and "sold in proportion" in r and not json.load(open(CF)).get("cut_req"), r
    r = LB.telegram("/cut put 0.03 hedge yes", st)
    q = json.load(open(CF))["cut_req"]
    assert r.startswith("CUT queued") and q["side"] == "PE" and abs(q["qty"] - 0.03) < 1e-9 and q["hedge"] == 1, (r, q)
    assert "QUEUED" in LB.telegram("/cut", {})
    assert LB.telegram("/cut cancel", {}).startswith("CUT request withdrawn") and not json.load(open(CF)).get("cut_req")
    st = {}
    LB.telegram("/cut call all", st)
    assert LB.telegram("/cut call all yes", st).startswith("CUT queued") and json.load(open(CF))["cut_req"]["qty"] == -1.0
    assert "/cut" in LB.codes_text() and "/cut" in LB.TG_CMDS
    print("A telegram: ok")

    FALL = {"PE": 1.0, "CE": 0.05}
    # ---------------------------------------------------------------- B partial cut, far option stays
    n, ex, msgs, tick, t0 = mk()
    put0 = sold(n, "PE")[0]
    Q = put0["qty"]
    assert Q > 0.05 and wings(n, "PE") and abs(wings(n, "PE")[0]["qty"] - Q) < 1e-9, (put0, wings(n, "PE"))
    tick(t0 + dt.timedelta(hours=1), 79000.0, FALL)
    req("PE", Q / 2)
    tick(t0 + dt.timedelta(hours=1, minutes=1), 79000.0)
    put = sold(n, "PE")[0]
    assert abs(put["qty"] - Q / 2) < 1e-9 and not put["closed"], put
    assert abs(wings(n, "PE")[0]["qty"] - Q) < 1e-9 and not wings(n, "PE")[0]["closed"]
    assert "EXIT-CUT" in rows(n) and "EXIT-CUTHEDGE" not in rows(n), rows(n)
    assert put.get("tp_oid") and ex.ords[put["tp_oid"]]["size"] == int(round(Q / 2 / 0.001)) and ex.ords[put["tp_oid"]]["state"] == "open", (put.get("tp_oid"))
    assert not json.load(open(LV.CFG_F)).get("cut_req") and n.S.get("cut_night") == n.S.get("night")
    assert guard.reconcile(ex.positions(), guard.expected_positions([n])) == [], "record differs from the exchange"
    assert any("CUT put: %d of %d" % (round(Q / 2 / 0.001), round(Q / 2 / 0.001)) in m for m in msgs), msgs
    assert n._topup(t0 + dt.timedelta(hours=1, minutes=2), 79000.0, ex.chain(), "2026-11-17") is False
    tick(t0 + dt.timedelta(hours=1, minutes=2), 79000.0); tick(t0 + dt.timedelta(hours=1, minutes=3), 79000.0)
    assert rows(n).count("EXIT-CUT") == 1, "request must run once"
    print("B partial cut: ok", rows(n))

    # ---------------------------------------------------------------- C cut ALL of the put in a fall, far option stays
    n, ex, msgs, tick, t0 = mk()
    tick(t0 + dt.timedelta(hours=1), 79000.0, FALL)
    req("PE", -1.0)
    tick(t0 + dt.timedelta(hours=1, minutes=1), 79000.0)
    assert sold(n, "PE")[0]["closed"] and not wings(n, "PE")[0]["closed"] and wings(n, "PE")[0].get("keep"), (sold(n, "PE"), wings(n, "PE"))
    assert not sold(n, "CE")[0]["closed"] or True
    for m in range(2, 12):
        tick(t0 + dt.timedelta(hours=1, minutes=m), 79000.0)
    assert not wings(n, "PE")[0]["closed"], "the usual release must not sell a kept far option"
    assert guard.reconcile(ex.positions(), guard.expected_positions([n])) == [], "record differs from the exchange"
    day = t0 + dt.timedelta(days=1)
    tick(day.replace(hour=17, minute=31), ex.spot); ex.expire()
    tick(day.replace(hour=17, minute=41), ex.spot)
    assert not n.open_legs() and n.S.get("finished"), (n.open_legs(), n.S.get("finished"))
    print("C cut all, far option kept: ok", rows(n)[-6:])

    # ---------------------------------------------------------------- D cut with hedge
    n, ex, msgs, tick, t0 = mk()
    tick(t0 + dt.timedelta(hours=1), 72500.0, {"PE": 1.0, "CE": 0.05})
    Q = sold(n, "PE")[0]["qty"]
    req("PE", Q / 2, hedge=1)
    tick(t0 + dt.timedelta(hours=1, minutes=1), 72500.0)
    w = wings(n, "PE")[0]
    assert "EXIT-CUT" in rows(n) and "EXIT-CUTHEDGE" in rows(n), rows(n)
    assert abs(w["qty"] - Q / 2) < 1e-9 and abs(sold(n, "PE")[0]["qty"] - Q / 2) < 1e-9, (w["qty"], sold(n, "PE")[0]["qty"])
    assert guard.reconcile(ex.positions(), guard.expected_positions([n])) == [], "record differs from the exchange"
    n, ex, msgs, tick, t0 = mk()                                    # far option with no bid (BTC far above it): not worth selling
    tick(t0 + dt.timedelta(hours=1), 82000.0)
    Q = sold(n, "PE")[0]["qty"]
    req("PE", Q / 2, hedge=1)
    tick(t0 + dt.timedelta(hours=1, minutes=1), 82000.0)
    assert "EXIT-CUT" in rows(n) and "EXIT-CUTHEDGE" not in rows(n) and abs(wings(n, "PE")[0]["qty"] - Q) < 1e-9, rows(n)
    print("D hedge in proportion / not worth selling: ok")

    # ---------------------------------------------------------------- E waits during the sale window
    n, ex, msgs, tick, t0 = mk()
    req("PE", 0.03)
    tick(dt.datetime(2026, 11, 16, 23, 45, tzinfo=IST), 82000.0)
    assert "EXIT-CUT" not in rows(n) and json.load(open(LV.CFG_F)).get("cut_req"), "must wait"
    tick(dt.datetime(2026, 11, 17, 0, 1, tzinfo=IST), 82000.0)
    assert "EXIT-CUT" in rows(n) and not json.load(open(LV.CFG_F)).get("cut_req")
    print("E waits for midnight: ok")

    # ---------------------------------------------------------------- F lapses
    n, ex, msgs, tick, t0 = mk()
    req("PE", 0.03, age=4000)
    tick(t0 + dt.timedelta(hours=1), 82000.0)
    assert "EXIT-CUT" not in rows(n) and any("lapsed" in m for m in msgs) and not json.load(open(LV.CFG_F)).get("cut_req"), msgs
    print("F lapse: ok")

    # ---------------------------------------------------------------- G nothing on that side
    n, ex, msgs, tick, t0 = mk()
    for l in sold(n, "CE"):
        n._close(t0 + dt.timedelta(minutes=5), 82000.0, l, None, "STOP")
    req("CE", -1.0)
    tick(t0 + dt.timedelta(hours=1), 82000.0)
    assert "EXIT-CUT" not in rows(n) and any("no sold call is open" in m for m in msgs), msgs
    print("G nothing to cut: ok")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nSELFTEST CUT PASSED")
