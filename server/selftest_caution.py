"""offline self-test of caution_patch (25-Nov-2026 c14): Telegram /caution and the flexible exit (letterbox.py + nightlive.py). Pretend exchange, throw-away folder, no real order.
 A Telegram: shows OFF; on -> caution 1; off -> 0; refusals
 B caution OFF: a sold call that has fallen to ~20 % of its sale price early in the night is NOT bought back (old behaviour, no EXIT-CAUTION)
 C caution ON, same night: BTC within 2-3 normal moves of the strike and the ask <= 25 % of the sale price -> bought back (EXIT-CAUTION), told, record = exchange, no halt
 D caution ON, ask about 35 % of the sale price: not bought back while 2-3 moves away (limit 25 %), bought back when the moves are bigger (z < 2, limit 40 %)
 E caution ON, late in the night (z >= 3): nothing, the call stays to its own 10 % order / the 17:20 exit
 F the setting switches itself off when the night ends"""
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




def night(name, juice, path, no_call_ask=False, extra=None, hv7=None):
    for d in ("state", "logs"):
        for f in os.listdir(tmp + "/" + d):
            os.remove(tmp + "/" + d + "/" + f)
    json.dump(dict(armed=True, acct="test", base=0.06, client="paper", rule="v5asl", wing=0.04, juice=juice, juice_every_s=0, retry_wait_s=0, polite_s=0,
                   fill_wait_s=0, wing_polite_s=0.05, wing_sell_every_s=0, **(extra or {})), open(LV.CFG_F, "w"))
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
    if hv7 is not None:
        IND["hv7"] = hv7
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
    info["cfg_end"] = json.load(open(LV.CFG_F))
    print("\n--- %s" % name)
    print("   sold options open after each stage:", snaps)
    print("   night P&L %.2f USD | halt: %s | events: %s" % (info["pnl"], info["halt"], " ".join(rows)))
    return info



import time, shutil as _sh
for f in ("letterbox.py", "nightlogic.py", "autosize.py", "control.py"):
    if os.path.exists(os.path.join(CODE, f)):
        _sh.copy(os.path.join(CODE, f), tmp)
sys.path.insert(0, tmp)
import letterbox as LB
CF = tmp + "/state/night_live_cfg.json"
try:
    json.dump(dict(armed=True, acct="test", base=0.06, rule="v5asl", wing=0.04), open(CF, "w"))
    json.dump(dict(night="2026-11-16", legs=[], halt=None, total_pnl=1.0, nights=1), open(tmp + "/state/night_nlive.json", "w"))
    assert "OFF" in LB.telegram("/caution", {})
    assert "ON for this night" in LB.telegram("/caution on", {}) and json.load(open(CF))["caution"] == 1
    assert "ON for this night" in LB.telegram("/caution", {})
    assert "OFF" in LB.telegram("/caution off", {}) and json.load(open(CF))["caution"] == 0
    assert LB.telegram("/caution maybe", {}).startswith("REFUSED") and "/caution" in LB.codes_text() and "/caution" in LB.TG_CMDS
    EARLY = [(1, 82000.0, 1.0, 0.20)]
    base_hv7 = IND["hv7"]
    b = night("B caution OFF: call down to ~20 %, early", 0.0, EARLY)
    assert "EXIT-CAUTION" not in b["rows"] and b["snaps"][0] == ["C", "P"], (b["snaps"], b["rows"])
    c = night("C caution ON: call at ~20 % of its price, 2-3 moves away -> bought back", 0.0, EARLY, extra=dict(caution=1))
    assert c["rows"].count("EXIT-CAUTION") >= 1 and "C" not in c["snaps"][0] and not c["halt"], (c["snaps"], c["rows"])
    assert any("CAUTION exit" in m for m in c["msgs"]), c["msgs"]
    assert c["cfg_end"]["caution"] == 0 and any("caution switched off" in m for m in c["msgs"]), c["cfg_end"]
    # D: ask about 35 %: not at z 2-3 (limit 25 %), yes when the expected move is bigger (hv7 high -> z below 2, limit 40 %)
    IND["hv7"] = base_hv7
    d1 = night("D1 caution ON, ask ~35 %, normal volatility", 0.0, [(1, 82000.0, 1.0, 0.33)], extra=dict(caution=1))
    d2 = night("D2 caution ON, ask ~35 %, high volatility (z < 2)", 0.0, [(1, 82000.0, 1.0, 0.33)], extra=dict(caution=1), hv7=1.6)
    print("   D1 events:", d1["rows"], "| D2 events:", d2["rows"])
    assert "EXIT-CAUTION" not in d1["rows"] and d1["snaps"][0] == ["C", "P"], (d1["snaps"], d1["rows"])
    assert d2["rows"].count("EXIT-CAUTION") >= 1 and not d2["halt"], (d2["snaps"], d2["rows"])
    # E: late in the night: far from the strike in normal moves
    IND["hv7"] = base_hv7
    e = night("E caution ON, 16 h after the sale (2 h left): z >= 3, call at ~20 %", 0.0, [(16, 82000.0, 1.0, 0.20)], extra=dict(caution=1))
    assert "EXIT-CAUTION" not in e["rows"], e["rows"]
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nSELFTEST CAUTION PASSED")
