"""offline self-test of juice_patch ("little premium left -> close the night"). Pretend exchange, throw-away folder, no network, no real order.
 1 rule ON 10 %  : put melts to 5 % (its resting order fills), call lingers at ~60 % of its own price -> still open (too much left);
                   call falls to ~15 % of its own price = under 10 % of the night's premium -> bought back at once (EXIT-JUICE),
                   far options handled by the old rule, record = exchange, no halt, night ends in profit
 2 rule OFF      : the same night -> the call stays open to the 17:20 exit (old behaviour, no EXIT-JUICE)
 3 rule ON, no asking price on the open call -> nothing is done
 4 rule ON, crash night -> the rule stays quiet (the open option is expensive), hedge and 17:20 exit work as before"""
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




def night(name, juice, path, no_call_ask=False):
    for d in ("state", "logs"):
        for f in os.listdir(tmp + "/" + d):
            os.remove(tmp + "/" + d + "/" + f)
    json.dump(dict(armed=True, acct="test", base=0.06, client="paper", rule="v5asl", wing=0.04, juice=juice, juice_every_s=0, retry_wait_s=0, polite_s=0,
                   fill_wait_s=0, wing_polite_s=0.05, wing_sell_every_s=0), open(LV.CFG_F, "w"))
    json.dump(dict(max_order_btc=0.36, max_open_btc=0.72, daily_loss_usd=60), open(guard.LIMITS_F, "w"))
    ex, msgs, clock = Fake(), [], [dt.datetime(2026, 11, 16, 23, 31, tzinfo=IST)]
    n = LV.LiveNight(ex, 0.06, lambda s, b="": msgs.append(s + " | " + b), lambda *a: None, sleep=lambda s: None, now_fn=lambda: clock[0])

    def tick(t, spot, late=False):
        clock[0] = t
        ex.spot, ex.late = spot, late
        n.step(t, spot, ex.chain(), IND)
        if n.open_legs():
            n.check_books("minute check")
    t0 = clock[0]
    tick(t0, 82000.0); tick(t0 + dt.timedelta(seconds=30), 82000.0)
    sold = [l for l in n.S["legs"] if l["dir"] == "S"]
    assert len(sold) == 2 and {l["side"] for l in sold} == {"PE", "CE"}, sold
    total = sum(l["entry"] * l["qty"] for l in sold)
    call = [l for l in sold if l["side"] == "CE"][0]
    snaps = []
    for i, (hrs, spot, mp, mc) in enumerate(path):
        ex.melt = {"PE": mp, "CE": mc}
        if no_call_ask:
            ex.no_ask.add(call["sym"])
        tick(t0 + dt.timedelta(hours=hrs), spot); tick(t0 + dt.timedelta(hours=hrs, minutes=1), spot)
        assert guard.reconcile(ex.positions(), guard.expected_positions([n])) == [], "record differs from the exchange"
        snaps.append(sorted(l["sym"][0] for l in n.open_legs() if l["dir"] == "S"))
    day = t0 + dt.timedelta(days=1)
    tick(day.replace(hour=17, minute=20, second=5), ex.spot); tick(day.replace(hour=17, minute=21), ex.spot)
    ex.expire()
    tick(day.replace(hour=17, minute=31), ex.spot); tick(day.replace(hour=17, minute=41), ex.spot)
    rows = [r["event"] for r in __import__("csv").DictReader(open(n.csv_path))]
    info = dict(snaps=snaps, rows=rows, msgs=msgs, halt=n.S.get("halt"), open_end=len(n.open_legs()), total=total,
                pnl=round((n.S.get("last_night") or {}).get("pnl", 0.0), 2), call_entry=call["entry"], call_exit=call.get("exit"))
    print("\n--- %s" % name)
    print("   sold options open after each stage:", snaps)
    print("   night P&L %.2f USD | halt: %s | events: %s" % (info["pnl"], info["halt"], " ".join(rows)))
    return info


try:
    CALM = [(1, 82000.0, 1.0, 1.0), (6, 82000.0, 0.05, 0.60), (9, 82000.0, 0.05, 0.15)]
    a = night("1 rule ON (10 %): put closed, call lingers, then little is left", 0.10, CALM)
    assert a["snaps"] == [["C", "P"], ["C"], []], a["snaps"]
    assert a["rows"].count("EXIT-JUICE") == 1 and a["rows"].count("EXIT-90PCT") == 1 and "EXIT-UE" not in a["rows"], a["rows"]
    assert any("little premium left" in m for m in a["msgs"]) and not a["halt"] and a["open_end"] == 0 and a["pnl"] > 0
    assert a["call_exit"] > 0.10 * a["call_entry"], "the call was bought back above its own 10 % order, by the night-level rule"
    print("   => call sold @ %.1f bought back @ %.1f when under 10 %% of the night's premium (%.2f USD) was left" % (a["call_entry"], a["call_exit"], a["total"]))

    b = night("2 rule OFF: same night, old behaviour", 0.0, CALM)
    assert b["snaps"] == [["C", "P"], ["C"], ["C"]] and "EXIT-JUICE" not in b["rows"] and "EXIT-UE" in b["rows"], (b["snaps"], b["rows"])
    assert not b["halt"] and b["open_end"] == 0

    c = night("3 rule ON, no asking price on the open call", 0.10, CALM, no_call_ask=True)
    assert "EXIT-JUICE" not in c["rows"] and not c["halt"] and c["open_end"] == 0, c["rows"]

    d = night("4 rule ON, crash night (BTC -12 %)", 0.10, [(1, 80000.0, 1.0, 1.0), (2, 77000.0, 1.0, 1.0), (3, 72200.0, 1.0, 1.0)])
    assert "EXIT-JUICE" not in d["rows"] and not d["halt"] and d["open_end"] == 0 and d["pnl"] < 0, d["rows"]
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nSELFTEST JUICE PASSED")
