"""offline self-test of takeprofit_patch (25-Nov-2026 c13): Telegram /takeprofit x (letterbox.py) and the one-night clearing in nightlive.py.
Pretend exchange, throw-away folder, no network, no real order.
 A Telegram: no setting -> shows OFF; /takeprofit 80 -> juice 0.2, this night only; 80 always; off; refusals (96, abc, 80 sometimes); 0 and 20 ask first and need 'yes' (also wrong text / late yes refused)
 B night with /takeprofit 90 (one night): put melts, call falls under 10 % of the premium -> closed (EXIT-JUICE); afterwards juice back to the old value and juice_once 0
 C standing 'always' setting: stays after the night
 D /takeprofit 0 (close now) on a calm night: everything sold is bought back at the first check even though the premium left is not small; clears afterwards
 E /takeprofit 0 on a crash night (position at a loss): still closes (the rule does not wait for a profit)"""
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




def night(name, juice, path, no_call_ask=False, extra=None):
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
    info["cfg_end"] = json.load(open(LV.CFG_F))
    print("   night P&L %.2f USD | halt: %s | events: %s" % (info["pnl"], info["halt"], " ".join(rows)))
    return info



import time, shutil as _sh
for f in ("letterbox.py", "nightlogic.py", "autosize.py", "control.py"):
    if os.path.exists(os.path.join(CODE, f)):
        _sh.copy(os.path.join(CODE, f), tmp)
sys.path.insert(0, tmp)
import letterbox as LB
assert LB.HOME == tmp
CF = tmp + "/state/night_live_cfg.json"


def cf():
    return json.load(open(CF))


try:
    # ---- A: Telegram wrapper
    json.dump(dict(armed=True, acct="test", base=0.06, rule="v5asl", wing=0.04, juice=0.0), open(CF, "w"))
    json.dump(dict(night="2026-11-16", legs=[], halt=None, total_pnl=1.0, nights=1), open(tmp + "/state/night_nlive.json", "w"))
    st = {}
    assert "off" in LB.telegram("/takeprofit", st).lower()
    r = LB.telegram("/takeprofit 80", st); print(r); assert "TAKE-PROFIT set" in r and cf()["juice"] == 0.2 and cf()["juice_once"] == 1 and cf()["juice_keep"] == 0.0
    assert "this night only" in LB.telegram("/takeprofit", st)
    r = LB.telegram("/takeprofit 85 always", st); assert cf()["juice"] == 0.15 and cf()["juice_once"] == 0, cf()
    r = LB.telegram("/takeprofit 70", st); assert cf()["juice"] == 0.3 and cf()["juice_once"] == 1 and cf()["juice_keep"] == 0.15, cf()   # old standing 15 % is kept
    assert "OFF" in LB.telegram("/takeprofit off", st) and cf()["juice"] == 0 and cf()["juice_once"] == 0
    for bad in ("96", "abc", "80 sometimes", "-5", "80 always always always"):
        assert LB.telegram("/takeprofit " + bad, st).startswith("REFUSED"), bad
    assert cf()["juice"] == 0
    r = LB.telegram("/takeprofit 0", st); print(r); assert "asks" in r and cf()["juice"] == 0
    r = LB.telegram("/takeprofit 20 yes", st); assert "asks" in r and cf()["juice"] == 0          # yes for something that was not asked
    r = LB.telegram("/takeprofit 0 yes", st); assert "asks" in r and cf()["juice"] == 0           # the ask above was for 20
    r = LB.telegram("/takeprofit 0", st); r = LB.telegram("/takeprofit 0 yes", st); assert "TAKE-PROFIT set" in r and cf()["juice"] == 1000.0 and cf()["juice_once"] == 1, cf()
    st["tp_ask"] = 0; LB.telegram("/takeprofit off", st)
    LB.telegram("/takeprofit 25", st); st["tp_ask"] = time.time() - 400
    assert "asks" in LB.telegram("/takeprofit 25 yes", st) and cf()["juice"] == 0               # a late yes is not accepted
    assert "/takeprofit" in LB.codes_text() and "/takeprofit" in LB.TG_CMDS
    LB.telegram("/takeprofit 80", {})

    # ---- B: a one-night setting works and clears
    CALM = [(1, 82000.0, 1.0, 1.0), (6, 82000.0, 0.05, 0.60), (9, 82000.0, 0.05, 0.15)]
    ONCE = dict(juice_once=1, juice_keep=0.0)
    b = night("B /takeprofit 90 (one night): closes when under 10 % is left, then clears", 0.10, CALM, extra=ONCE)
    assert b["rows"].count("EXIT-JUICE") == 1 and not b["halt"] and b["open_end"] == 0 and b["pnl"] > 0, b["rows"]
    assert b["cfg_end"]["juice"] == 0.0 and b["cfg_end"]["juice_once"] == 0, b["cfg_end"]
    assert any("take-profit cleared" in m for m in b["msgs"]), b["msgs"]
    # C: standing keeps
    c = night("C standing (always) 10 %: stays after the night", 0.10, CALM)
    assert "EXIT-JUICE" in c["rows"] and c["cfg_end"]["juice"] == 0.10, c["cfg_end"]
    # D: close now on a calm night
    d = night("D /takeprofit 0: everything sold is bought back at the first check", 1000.0, [(1, 82000.0, 1.0, 1.0), (6, 82000.0, 0.05, 0.60)], extra=dict(juice_once=1, juice_keep=0.0))
    assert d["snaps"][0] == [] and d["rows"].count("EXIT-JUICE") >= 2 and not d["halt"] and d["open_end"] == 0, (d["snaps"], d["rows"])
    assert d["cfg_end"]["juice"] == 0.0 and d["cfg_end"]["juice_once"] == 0, d["cfg_end"]
    # E: close now on a crash night (loss)
    e = night("E /takeprofit 0 on a crash night: closes although at a loss", 1000.0, [(1, 80000.0, 1.0, 1.0), (2, 77000.0, 1.0, 1.0)], extra=dict(juice_once=1, juice_keep=0.0))
    assert e["snaps"][0] == [] and not e["halt"] and e["open_end"] == 0, (e["snaps"], e["rows"])
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nSELFTEST TAKEPROFIT PASSED")
