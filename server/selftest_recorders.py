"""offline self-test of the paperplus live recorders (postfill prices, hedge availability). Harness: offline self-test of guardrule_patch (guard at sold strike while a side is unhedged, back to 2 x ATR when hedged). Harness: offline self-test of hedgerule_patch (hedge-exists rule, once-per-night message, retry log, 5.5 units) on top of livefl_patch. Harness from livefl test: offline self-test of livefl_patch (live size flags, switch off/f/h) on top of wing selftest harness. ORIGINAL DOC: wing_live_patch. A pretend exchange (no network, no key, no real order) and a throw-away folder for all files.
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
        self.spot, self.pos, self.ords, self.nid, self.no_ask, self.wing_px, self.late, self.late_bid = 82000.0, {}, {}, 1, set(), None, False, 0.0

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



import csv, datetime as _d
def hist(high):
    p = tmp + "/state/"
    lv = 0.02 if not high else 0.00001
    # premium history (% of BTC) and iv history; 120 nights. high=True -> tonight is the richest ever; False -> tonight is the cheapest
    base = (0.0001 if high else 5.0)
    with open(p + "prem_hist.csv", "w") as f:
        for i in range(120):
            d = (_d.date(2026, 11, 16) - _d.timedelta(days=i + 1)).isoformat()
            f.write("%s,%s,delta,x\n" % (d, base + 0.0001 * i))
    with open(p + "iv_hist.csv", "w") as f:
        for i in range(120):
            d = (_d.date(2026, 11, 16) - _d.timedelta(days=i + 1)).isoformat()
            f.write("%s,%s,delta,x\n" % (d, (0.1 if high else 5.0) + 0.001 * i))


def run(mode, rsi, high, wing, cut=None):
    for f in os.listdir(tmp + "/state"): os.remove(tmp + "/state/" + f)
    for f in os.listdir(tmp + "/logs"): os.remove(tmp + "/logs/" + f)
    json.dump(dict(armed=True, acct="test", base=0.06, client="paper", rule="v5asl", wing=wing, flagmode=mode, retry_wait_s=0, polite_s=0, fill_wait_s=0, wing_polite_s=0), open(LV.CFG_F, "w"))
    json.dump(dict(max_order_btc=0.36, max_open_btc=0.72, daily_loss_usd=60), open(guard.LIMITS_F, "w"))
    hist(high)
    ex, msgs, clock = Fake(), [], [dt.datetime(2026, 11, 16, 23, 31, tzinfo=IST)]
    n = LV.LiveNight(ex, 0.06, lambda s, b="": msgs.append(s + " | " + b), lambda *a: None, sleep=lambda s: None, now_fn=lambda: clock[0])
    ind = dict(IND, rsi4h=rsi)
    def chain():
        c = ex.chain()
        if cut:   # Delta-like: nothing listed beyond the strike the rule sells (both types cut at the same distance)
            c = [o for o in c if not ((o["typ"] == "PE" and o["strike"] < cut[0]) or (o["typ"] == "CE" and o["strike"] > cut[1]))]
        return c
    for k in range(3):
        n.step(clock[0] + dt.timedelta(seconds=30 * k), 82000.0, chain(), ind)
    sold = {l["set"]: l for l in n.S["legs"] if l["dir"] == "S"}
    return sold, msgs, n



try:
    s1, m1, n1 = run("off", 50.0, False, 0.04)
    t = dt.datetime(2026, 11, 17, 0, 5, tzinfo=IST)
    n1._record(t, 82000.0, n1.cl.chain())
    rows = list(csv.DictReader(open(os.path.join(tmp, "logs", "hedge_exists.csv"))))
    assert {r["side"] for r in rows} == {"PE", "CE"} and all(int(r["far_listed"]) > 0 for r in rows), rows
    n1._record(t, 82000.0, n1.cl.chain())
    assert len(list(csv.DictReader(open(os.path.join(tmp, "logs", "hedge_exists.csv"))))) == 2
    print("--- 1 far-option availability written once per night, both sides")
    put = [l for l in n1.S["legs"] if l["dir"] == "S" and l["side"] == "PE" and not l["closed"]][0]
    n1._tp_book(t, put, int(round(put["qty"] / LV.C)), round(put["entry"] * 0.1, 1), 0.0)
    assert n1.S["postfill"] and n1.S["postfill"][-1]["sym"] == put["sym"]
    n1._pf_t = 0
    n1._record(t, 81900.0, n1.cl.chain())
    pr = list(csv.DictReader(open(os.path.join(tmp, "logs", "postfill_prices.csv"))))
    assert pr and pr[-1]["sym"] == put["sym"], pr
    print("--- 2 after a 90 % buy-back fill the option price is recorded every 5 minutes")
    print("SELFTEST RECORDERS PASSED")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
