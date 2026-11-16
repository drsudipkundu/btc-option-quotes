"""offline self-test of wing_live_patch. A pretend exchange (no network, no key, no real order) and a throw-away folder for all files.
Six nights are played through the REAL live-seller class:
 1 calm night, hedge on   : both sales get a far option; record = exchange; crash guard buys nothing; sold options bought back at 10 %;
                            far options stay, are NOT sold cheap, expire; no halt after 17:30
 2 crash night, hedge on  : BTC -12 %; crash guard buys nothing more; 17:20 exit buys the put back and sells the far put; loss is capped
 3 same crash, hedge off  : exactly the old behaviour (crash guard buys insurance late); loss is much bigger
 4 no offers at far strikes: sale stands, 'hedge not complete' told, crash guard still fires
 5 far option too costly  : not bought
 6 size limit too small   : sale stands, hedge refused by the guard, told"""
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
        self.spot, self.pos, self.ords, self.nid, self.no_ask, self.wing_px, self.late = 82000.0, {}, {}, 1, set(), None, False

    def px(self, typ, k):
        d = (self.spot - k) / self.spot if typ == "PE" else (k - self.spot) / self.spot      # > 0 = out of the money
        if d <= 0:
            return (k - self.spot if typ == "PE" else self.spot - k) + 30.0
        v = 3000.0 * max(0.0, 0.06 - d)
        if self.late:
            v *= 0.05
        return v

    def quote(self, s):
        p = s.split("-"); typ, k = ("PE" if p[0] == "P" else "CE"), float(p[2])
        v = self.px(typ, k)
        bid = round(v, 1) if v >= 1.0 else 0.0
        ask = round(v * 1.05 + 0.5, 1)
        if v < 1.0 and self.wing_px:
            ask = self.wing_px
        if s in self.no_ask or (self.late and v < 1.0):
            ask = 0.0
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


def night(name, wing, crash=False, limits=None, no_far_ask=False, wing_px=None):
    for f in os.listdir(tmp + "/state"):
        os.remove(tmp + "/state/" + f)
    for f in os.listdir(tmp + "/logs"):
        os.remove(tmp + "/logs/" + f)
    json.dump(dict(armed=True, acct="test", base=0.06, client="paper", rule="v5asl", wing=wing, retry_wait_s=0, polite_s=0, fill_wait_s=0), open(LV.CFG_F, "w"))
    json.dump(limits or dict(max_order_btc=0.36, max_open_btc=0.72, daily_loss_usd=60), open(guard.LIMITS_F, "w"))
    ex, msgs, clock = Fake(), [], [dt.datetime(2026, 11, 16, 23, 31, tzinfo=IST)]
    ex.wing_px = wing_px
    if no_far_ask:
        for k in range(60000, 100001, 200):
            if 75000 <= k <= 77000:
                ex.no_ask.add(sym("PE", k))
            if 87000 <= k <= 89200:
                ex.no_ask.add(sym("CE", k))
    n = LV.LiveNight(ex, 0.06, lambda s, b="": msgs.append(s + " | " + b), lambda *a: None, sleep=lambda s: None, now_fn=lambda: clock[0])

    def tick(t, spot, late=False):
        clock[0] = t
        ex.spot, ex.late = spot, late
        n.step(t, spot, ex.chain(), IND)
        if n.open_legs():
            n.check_books("minute check")
    t0 = clock[0]
    tick(t0, 82000.0)
    tick(t0 + dt.timedelta(seconds=30), 82000.0)
    sold = [l for l in n.S["legs"] if l["dir"] == "S"]
    wings = [l for l in n.S["legs"] if l["dir"] == "B"]
    assert len(sold) == 2 and {l["side"] for l in sold} == {"PE", "CE"}, sold
    assert abs(sum(l["qty"] for l in sold) - 0.24) < 1e-9
    assert not n.S.get("halt") or limits, n.S.get("halt")
    assert guard.reconcile(ex.positions(), guard.expected_positions([n])) == [], "record differs from the exchange"
    info = dict(sold=[(l["sym"], l["qty"], l["entry"]) for l in sold], wings=[(l["sym"], l["qty"], l["entry"]) for l in wings])
    day = t0 + dt.timedelta(days=1)
    if crash:
        for i, s in enumerate((80000.0, 77000.0, 74000.0, 72200.0)):
            tick(t0 + dt.timedelta(hours=1 + i), s)
        info["after_crash"] = [(l["sym"], l["dir"], l["qty"]) for l in n.open_legs()]
        tick(day.replace(hour=17, minute=20, second=5), 72200.0)
        tick(day.replace(hour=17, minute=21, second=0), 72200.0)
    else:
        tick(t0 + dt.timedelta(hours=1), 82000.0)
        tick(day.replace(hour=9, minute=0), 82000.0, late=True)        # premiums have melted: the 10 % resting orders fill
        tick(day.replace(hour=9, minute=1), 82000.0, late=True)
        info["after_buyback"] = [(l["sym"], l["dir"], l["qty"]) for l in n.open_legs()]
        tick(day.replace(hour=17, minute=20, second=5), 82000.0, late=True)
        info["after_1720"] = [(l["sym"], l["dir"], l["qty"]) for l in n.open_legs()]
    ex.expire()
    tick(day.replace(hour=17, minute=31), ex.spot, late=True)
    info["halt_after_expiry"] = n.S.get("halt")
    tick(day.replace(hour=17, minute=41), ex.spot, late=True)
    info.update(open_end=len(n.open_legs()), pnl=round((n.S.get("last_night") or {}).get("pnl", 0.0), 2), halt=n.S.get("halt"),
                msgs=msgs, rows=[r["event"] for r in __import__("csv").DictReader(open(n.csv_path))] if os.path.exists(n.csv_path) else [])
    print("\n--- %s" % name)
    print("   sold   :", info["sold"])
    print("   bought :", info["wings"])
    print("   night P&L %.2f USD | halt: %s | events: %s" % (info["pnl"], info["halt"], " ".join(info["rows"])))
    return info


try:
    a = night("1 calm night, hedge ON", 0.04)
    assert len(a["wings"]) == 2 and abs(sum(w[1] for w in a["wings"]) - 0.24) < 1e-9
    for (ss, sq, sp), (ws, wq, wp) in zip(sorted(a["sold"]), sorted(a["wings"])):
        ks, kw = float(ss.split("-")[2]), float(ws.split("-")[2])
        assert ss[0] == ws[0] and abs(sq - wq) < 1e-9 and abs(kw - ks) >= 0.04 * 82000 - 1e-6 and abs(kw - ks) <= 0.04 * 82000 + 200, (ss, ws)
        assert wp <= 0.5 * sp
    assert all(x[1] == "B" for x in a["after_buyback"]) and len(a["after_buyback"]) == 2, a["after_buyback"]
    assert len(a["after_1720"]) == 2 and a["open_end"] == 0 and not a["halt"] and not a["halt_after_expiry"]
    assert "SETTLE-WING" in a["rows"] and a["rows"].count("EXIT-90PCT") == 2 and a["pnl"] > 0
    assert not any("CRASH GUARD" in m for m in a["msgs"])

    b = night("2 crash night (BTC -12 %), hedge ON", 0.04, crash=True)
    assert len(b["wings"]) == 2 and not any("CRASH GUARD" in m for m in b["msgs"]), "crash guard must stay quiet when fully hedged"
    assert b["open_end"] == 0 and not b["halt"] and not b["halt_after_expiry"]
    c = night("3 same crash, hedge OFF (old behaviour)", 0.0, crash=True)
    assert not c["wings"] and any("CRASH GUARD" in m for m in c["msgs"]) and c["open_end"] == 0 and not c["halt"]
    put = [s for s in b["sold"] if s[0].startswith("P")][0]
    width = 0.04 * 82000 + 200
    assert b["pnl"] > -(width * put[1]) - 80, "hedged loss must be capped near strike gap x size (plus the pretend 5 % buy-back spread)"
    assert c["pnl"] < b["pnl"] - 100, "unhedged crash must lose far more"
    print("   => crash night: hedged %.2f USD against unhedged %.2f USD (cap = strike gap %.0f x %.2f BTC = %.0f USD less premium)" % (
        b["pnl"], c["pnl"], width, put[1], width * put[1]))

    d = night("4 no offers at the far strikes, hedge ON", 0.04, crash=True, no_far_ask=True)
    assert any("HEDGE NOT COMPLETE" in m for m in d["msgs"]) and not d["halt"] and d["open_end"] == 0
    assert any("CRASH GUARD" in m for m in d["msgs"]) or len(d["wings"]) >= 1

    e = night("5 far option too costly, hedge ON", 0.04, wing_px=60.0)
    assert not e["wings"] and any("too costly" in m for m in e["msgs"]) and not e["halt"] and e["open_end"] == 0

    f = night("6 size limit too small for the hedge", 0.04, limits=dict(max_order_btc=0.36, max_open_btc=0.30, daily_loss_usd=60))
    assert any("size limit" in m for m in f["msgs"]) and not f["halt"] and f["open_end"] == 0
    assert abs(sum(s[1] for s in f["sold"]) - 0.24) < 1e-9
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nSELFTEST WING PASSED")
