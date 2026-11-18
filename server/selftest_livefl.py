"""offline self-test of livefl_patch (live size flags, switch off/f/h) on top of wing selftest harness. ORIGINAL DOC: wing_live_patch. A pretend exchange (no network, no key, no real order) and a throw-away folder for all files.
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

def run(mode, rsi, high):
    for f in os.listdir(tmp + "/state"): os.remove(tmp + "/state/" + f)
    for f in os.listdir(tmp + "/logs"): os.remove(tmp + "/logs/" + f)
    json.dump(dict(armed=True, acct="test", base=0.06, client="paper", rule="v5asl", wing=0.0, flagmode=mode, retry_wait_s=0, polite_s=0, fill_wait_s=0), open(LV.CFG_F, "w"))
    json.dump(dict(max_order_btc=0.36, max_open_btc=0.72, daily_loss_usd=60), open(guard.LIMITS_F, "w"))
    hist(high)
    ex, msgs, clock = Fake(), [], [dt.datetime(2026, 11, 16, 23, 31, tzinfo=IST)]
    n = LV.LiveNight(ex, 0.06, lambda s, b="": msgs.append(s + " | " + b), lambda *a: None, sleep=lambda s: None, now_fn=lambda: clock[0])
    ind = dict(IND, rsi4h=rsi)
    n.step(clock[0], 82000.0, ex.chain(), ind)
    n.step(clock[0] + dt.timedelta(seconds=30), 82000.0, ex.chain(), ind)
    sold = {l["set"]: l for l in n.S["legs"] if l["dir"] == "S"}
    return sold, msgs, n

try:
    s0, m0, _ = run("off", 70.0, True)
    assert abs(s0["trend"]["qty"] - 0.18) < 1e-9 and abs(s0["extra"]["qty"] - 0.06) < 1e-9, s0
    print("--- 1 switch off, every flag on: trend 0.18 (3 x base), opposite 0.06 - exactly as before")
    s1, m1, _ = run("f", 70.0, False)
    assert abs(s1["trend"]["qty"] - 0.27) < 1e-9 and abs(s1["extra"]["qty"] - 0.06) < 1e-9, s1
    assert any("x 1.5 tonight" in m and "paper" not in m for m in m1), m1
    print("--- 2 mode F, RSI flag on: trend 0.27 (4.5 x base), opposite unchanged, message says live")
    s2, m2, _ = run("f", 50.0, False)
    assert abs(s2["trend"]["qty"] - 0.18) < 1e-9, s2
    print("--- 3 mode F, no flag: trend stays 0.18")
    s3, m3, _ = run("h", 50.0, False)
    assert abs(s3["trend"]["qty"] - 0.09) < 1e-9 and abs(s3["extra"]["qty"] - 0.06) < 1e-9, s3
    print("--- 4 mode H, no flag: trend 0.09 (half), opposite unchanged")
    s4, m4, _ = run("h", 70.0, True)
    assert abs(s4["trend"]["qty"] - 0.27) < 1e-9, s4
    print("--- 5 mode H, flags on: trend 0.27")
    import autosize as AS
    json.dump(dict(flagmode="f"), open(tmp + "/state/night_live_cfg.json", "w"))
    assert AS.limits_for(0.19) == dict(max_order_btc=0.95, max_open_btc=2.28), AS.limits_for(0.19)
    json.dump(dict(flagmode="off"), open(tmp + "/state/night_live_cfg.json", "w"))
    assert AS.limits_for(0.19) == dict(max_order_btc=0.57, max_open_btc=1.52), AS.limits_for(0.19)
    print("--- 6 guard limits: mode F 5 x / 12 x base (0.95 / 2.28 at base 0.19); off 3 x / 8 x")
    print("SELFTEST LIVE FLAGS PASSED")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
