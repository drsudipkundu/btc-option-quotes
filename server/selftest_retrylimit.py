"""offline self-test of retrylimit_patch (25-Nov-2026 c12): retry hedge limited to a time-based share of the sold option's price NOW, 25 % buy-back, messages, old behaviour when switched off.
Harness from selftest_wingretry (pretend exchange, throw-away folder, REAL live-seller class). Far puts have no offers at the 23:31 sale; later a far put is offered at a chosen ask
while the sold put is worth a chosen share of its sale price. Cases:
 1 dear hedge refused (77 % of the sold put's price now), sold put still worth 60 % of the sale price -> not bought, one message, no buy-back
 2 cheap hedge (20 % of its price now) 3 h after the sale -> bought, no buy-back
 3 limit rises with the hours: ask 55 % of the price now is refused 6 h after the sale (limit 40 %/50 %) and bought with 1 h left (limit 75 %)
 4 sold put melts to 20 % of its sale price, no hedge passes -> bought back (BB25), told, side has no risk
 5 switch off (retry_lim 0) -> old ceiling (30 % of the SALE price) decides
 6 retry_bb 0 -> no buy-back even when the sold put has melted"""
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






def night(name, retry_cfg, hours, melt_put, hedge_ask_share):
    """sale at 23:31; far puts blocked; at 'hours' after the sale far puts come on offer at hedge_ask_share x the sold put's ask NOW"""
    for d in ("state", "logs"):
        for f in os.listdir(tmp + "/" + d):
            os.remove(tmp + "/" + d + "/" + f)
    cfgd = dict(armed=True, acct="test", base=0.06, client="paper", rule="v5asl", wing=0.04, juice=0.0, juice_every_s=0, wing_retry_s=0,
                retry_wait_s=0, polite_s=0, fill_wait_s=0, wing_polite_s=0.05, wing_sell_every_s=0)
    cfgd.update(retry_cfg)
    json.dump(cfgd, open(LV.CFG_F, "w"))
    json.dump(dict(max_order_btc=0.36, max_open_btc=0.72, daily_loss_usd=60), open(guard.LIMITS_F, "w"))
    ex, msgs, clock = Fake(), [], [dt.datetime(2026, 11, 16, 23, 31, tzinfo=IST)]
    blocked = {sym("PE", k) for k in range(60000, 82000, 200)}
    ex.no_ask |= blocked
    n = LV.LiveNight(ex, 0.06, lambda s, b="": msgs.append(s + " | " + b), lambda *a: None, sleep=lambda s: None, now_fn=lambda: clock[0])

    def tick(t, spot):
        clock[0] = t
        ex.spot = spot
        n.step(t, spot, ex.chain(), IND)
        if n.open_legs():
            n.check_books("minute check")
    t0 = clock[0]
    tick(t0, 82000.0); tick(t0 + dt.timedelta(seconds=30), 82000.0)
    put = [l for l in n.S["legs"] if l["dir"] == "S" and l["side"] == "PE" and l.get("kind") != "ins"]
    assert put, "no put sold"
    entry = put[0]["entry"]
    # the sold put melts; far puts come on offer at the chosen share of the sold put's ask
    ex.melt["PE"] = melt_put
    ex.no_ask.discard(put[0]["sym"])
    cur = ex.ticker(put[0]["sym"])["ask"]
    ex.wing_px = round(max(0.1, hedge_ask_share * cur), 1)
    ex.no_ask -= blocked
    tick(t0 + dt.timedelta(hours=hours), 82000.0); tick(t0 + dt.timedelta(hours=hours, minutes=1), 82000.0)
    wing = round(sum(l["qty"] for l in n.S["legs"] if l.get("kind") == "wing" and l["side"] == "PE"), 3)
    pe = [l for l in n.S["legs"] if l["dir"] == "S" and l["side"] == "PE" and l.get("kind") != "ins"]
    closed = bool(pe and pe[0]["closed"])
    assert guard.reconcile(ex.positions(), guard.expected_positions([n])) == [], "record differs from the exchange"
    ref = sum("RETRY HEDGE REFUSED" in m for m in msgs)
    bb = sum("RETRY BUY-BACK" in m for m in msgs)
    print("\n--- %s\n   sold put @ %.1f now %.1f (%.0f %%), far put ask %.1f; hedge bought %.3f | put closed %s | refused msgs %d | buy-back msgs %d | halt %s" % (
        name, entry, cur, cur / entry * 100, ex.wing_px, wing, closed, ref, bb, n.S.get("halt")))
    return wing, closed, ref, bb, n.S.get("halt"), msgs, entry, cur


try:
    # 1 dear hedge refused
    w, c, ref, bb, halt, m, e, cur = night("1 dear hedge (77 % of the price now) refused, put worth 60 % of sale", {}, 3, 0.6, 0.77)
    assert w == 0 and not c and ref == 1 and bb == 0 and not halt, (w, c, ref, bb)
    # 2 cheap hedge bought
    w, c, ref, bb, halt, m, e, cur = night("2 cheap hedge (20 % of the price now), put worth 60 %", {}, 3, 0.6, 0.20)
    assert w > 0 and not c and bb == 0 and not halt, (w, c, bb)
    # 3 limit rises with the hours: ask 55 % of the price now
    w, c, ref, bb, halt, m, e, cur = night("3a 6 h after the sale (about 12 h left, limit 30 %) ask 55 %", {}, 6, 0.6, 0.55)
    assert w == 0 and ref == 1, (w, ref)
    w, c, ref, bb, halt, m, e, cur = night("3b 17 h after the sale (about 1 h left would be stopped - use 15.5 h, limit 60 %) ask 55 %", {}, 15.4, 0.6, 0.55)
    assert w > 0 and not c, (w, c)
    # 4 sold put melts to 20 % of the sale price, hedge too dear -> buy-back
    w, c, ref, bb, halt, m, e, cur = night("4 put melts to 20 % of the sale price, hedge too dear -> bought back", {}, 3, 0.15, 0.90)
    assert w == 0 and c and bb == 1 and not halt, (w, c, bb)
    assert any("EXIT-BB25" in open(tmp + "/logs/" + f).read() for f in os.listdir(tmp + "/logs") if f.endswith(".csv")), "no BB25 row in the trade log"
    # 5 switched off: old ceiling = 30 % of the SALE price decides (put worth 60 % of sale, hedge ask 20 % of price now = 12 % of sale -> bought; 77 % of now = 46 % of sale -> refused by the OLD ceiling)
    w, c, ref, bb, halt, m, e, cur = night("5a switch off, ask 20 % of now -> old ceiling lets it pass", dict(retry_lim=0), 3, 0.6, 0.20)
    assert w > 0 and ref == 0 and bb == 0, (w, ref, bb)
    w, c, ref, bb, halt, m, e, cur = night("5b switch off, ask 77 % of now (46 % of sale) -> old ceiling refuses, no new message", dict(retry_lim=0), 3, 0.6, 0.77)
    assert w == 0 and ref == 0 and bb == 0 and not c, (w, ref, bb, c)
    # 6 buy-back off
    w, c, ref, bb, halt, m, e, cur = night("6 retry_bb 0: no buy-back even when the put has melted", dict(retry_bb=0), 3, 0.15, 0.90)
    assert w == 0 and not c and bb == 0, (w, c, bb)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nSELFTEST RETRY LIMIT PASSED")
