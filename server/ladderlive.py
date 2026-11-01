#!/usr/bin/env python3
"""LIVE-MONEY ladder runner (1-Nov-2026) - ready, but every ladder starts DISARMED (no orders at all).
Runs the same ladder logic as the paper bots (v9 = bot.py, v10/v11/v12 = variants.py) on a real Delta sub-account:
  - ladder buys/sells as resting POST-ONLY limit orders (maker fee; an order that would cross is rejected, re-placed next tick)
  - fills read from the exchange (partial fills handled), trades -> logs/trades_live_<key>.csv, state -> state/live_<key>_state.json
  - the CE leg (ladcall.py, v9 CALL v3 rules) with Smart Sell on real orders, if "calls" is on
  - SAFETY: per-order size limit, total-hold limit (= ladder brake), position check every minute (BTCUSD and the calls):
    any mismatch cancels all orders and HALTS that ladder until you clear it; STOP file / Pause All pauses it.
    Pausing or halting never sells BTC - holdings stay; only orders are cancelled.
Config: state/ladder_live_cfg.json (edit only through the commands below).
Commands (on the server, in ~/deltabot):
  venv/bin/python ladderlive.py --status
  venv/bin/python ladderlive.py --check ladder            read-only look at the account the ladder would use
  venv/bin/python ladderlive.py --arm ladder --acct ladder9   (only with Sudip's yes)
  venv/bin/python ladderlive.py --disarm ladder
  venv/bin/python ladderlive.py --clear-halt ladder
  venv/bin/python ladderlive.py --selftest ladder --yes   one 1-contract post-only buy 5% below the bid, then cancel
Keys: lv10 / lv11 / lv12 work the same way."""
import os, sys, json, time, csv, math, logging, datetime as dt
from logging.handlers import RotatingFileHandler

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
CFG_F = os.path.join(HOME, "state", "ladder_live_cfg.json")
SYM = "BTCUSD"
C = 0.001
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
KEYS = ("ladder", "lv10", "lv11", "lv12")
DEF = dict(armed=False, acct="ladder9", calls=True, max_order_btc=0.01, max_hold_btc=None, halt=None)
log = logging.getLogger("ladderlive")

def load_cfg():
    try:
        d = json.load(open(CFG_F))
    except Exception:
        d = {}
    return {k: dict(DEF, **d.get(k, {})) for k in KEYS}

def save_cfg(c):
    os.makedirs(os.path.dirname(CFG_F), exist_ok=True)
    json.dump(c, open(CFG_F + ".tmp", "w"), indent=1)
    os.replace(CFG_F + ".tmp", CFG_F)

def put(key, **kw):
    c = load_cfg()
    c[key].update(kw)
    save_cfg(c)
    return c[key]

def client_for(acct):
    import liveorders as LO

    class LiveX(LO.Live):
        def place(self, sym, side, size, price, reduce_only=False, cid=None, post_only=False):
            body = {"product_symbol": sym, "size": int(size), "side": side, "order_type": "limit_order",
                    "limit_price": ("%.4f" % price).rstrip("0").rstrip("."), "time_in_force": "gtc",
                    "reduce_only": bool(reduce_only)}
            if post_only:
                body["post_only"] = True
            if cid:
                body["client_order_id"] = cid
            return LO.norm(self._p("POST", "/v2/orders", body=body)["result"])

        def open_orders(self, sym=SYM):
            r = self._p("GET", "/v2/orders", {"product_ids": self.product(sym)["id"], "states": "open,pending"})["result"]
            return [LO.norm(o) for o in r or []]
    return LiveX(acct)

class Halt(Exception):
    pass

def make_live_class(base_cls, key):
    import bot as B

    class LiveBot(base_cls):
        def __init__(self, cl, cfg, feed, notifier):
            self.live_key, self.cl, self.cfg = key, cl, cfg
            self.live_state = os.path.join(HOME, "state", "live_%s_state.json" % key)
            self.live_trades = os.path.join(HOME, "logs", "trades_live_%s.csv" % key)
            self.last_rec = 0
            if key == "ladder":
                base_cls.__init__(self, feed, notifier)
            else:
                base_cls.__init__(self, key, feed, notifier)
            self.n = notifier
            import ladcall, ssjob
            ex = ssjob.LiveExec(cl, self.check_opt)
            self.calls = ladcall.CallLeg(key, notify=lambda s, b="": self.n.send("LIVE %s CALL %s" % (key, s), b),
                                         log=log.info, mode="live", ex=ex)

        # ---- own files (never the paper ones)
        def save(self):
            d = {"ladder": self.ladder.to_dict(), "orders": self.orders, "next_oid": self.next_oid,
                 "paused": self.paused, "last_summary_day": self.last_summary_day}
            json.dump(d, open(self.live_state + ".tmp", "w"))
            os.replace(self.live_state + ".tmp", self.live_state)

        def load(self):
            if not os.path.exists(getattr(self, "live_state", "")):
                return
            d = json.load(open(self.live_state))
            self.ladder.from_dict(d["ladder"])
            self.orders = {int(k): v for k, v in d["orders"].items()}
            self.next_oid = d["next_oid"]
            self.paused = d.get("paused", False)
            self.last_summary_day = d.get("last_summary_day")

        def log_trade(self, event, side, c, price, pnl=0.0, note="", fee=None):
            new = not os.path.exists(self.live_trades)
            if fee is None:
                fee = c * C * price * B.FEE_RATE
            with open(self.live_trades, "a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["time_ist", "mode", "event", "cycle", "side", "contracts", "price",
                                "fee_usd", "pnl_usd", "lots_after", "held_contracts", "note"])
                w.writerow([B.ist().strftime("%Y-%m-%d %H:%M:%S"), "LIVE", event, self.ladder.cycle, side, c,
                            "%.1f" % price, "%.4f" % fee, "%.4f" % pnl, len(self.ladder.lots), self.ladder.held(), note])
            return fee

        # ---- safety
        def max_hold_c(self):
            mh = self.cfg.get("max_hold_btc")
            return int(round(mh / C)) if mh else self.ladder.brake + self.ladder.entry_c

        def check_opt(self, sym, side, n, reduce_only):
            if reduce_only:
                return True
            if n * C > max(self.cfg["max_order_btc"], 0.3) + 1e-9:
                raise Halt("call order %d contracts above the limit" % n)
            return True

        def halt(self, why):
            self.cancel_all()
            self.cfg = put(self.live_key, halt=why)
            self.n.send("LIVE %s HALTED" % self.live_key, why + "\nAll orders cancelled. BTC holdings are kept. Clear with --clear-halt after checking.")
            log.error("HALT %s: %s", self.live_key, why)

        def reconcile(self, force=False):
            now = time.time()
            if not force and now - self.last_rec < 60:
                return True
            self.last_rec = now
            pos = self.cl.positions()
            real = int(round(pos.get(SYM, 0)))
            if real != self.ladder.held():
                self.halt("position mismatch: Delta %s %d contracts vs ladder %d" % (SYM, real, self.ladder.held()))
                return False
            exp = self.calls.expected_positions() if self.cfg.get("calls") else {}
            for s in set(exp) | {k for k in pos if str(k).startswith("C-BTC")}:
                if int(round(pos.get(s, 0))) != exp.get(s, 0):
                    self.halt("call position mismatch on %s: Delta %s vs bot %s" % (s, pos.get(s, 0), exp.get(s, 0)))
                    return False
            return True

        # ---- exchange-backed order book
        def place(self, side, price, c, tag, **extra):
            if c * C > self.cfg["max_order_btc"] + 1e-9:
                raise Halt("order %d contracts above the per-order limit %.3f BTC" % (c, self.cfg["max_order_btc"]))
            if side == "buy" and self.ladder.held() + c > self.max_hold_c():
                return None
            o = {"id": self.next_oid, "side": side, "price": price, "c": c, "tag": tag, "born": self.clock(), "filled": 0}
            o.update(extra)
            self.next_oid += 1
            try:
                r = self.cl.place(SYM, side, c, price, side == "sell", "L%s%d" % (self.live_key[:4], o["id"]), post_only=True)
            except Exception as e:
                log.warning("%s place %s %d @ %.1f failed: %s", self.live_key, side, c, price, e)
                return None
            o["xid"] = r["id"]
            if r["state"] in ("cancelled", "rejected"):  # post-only would have crossed
                return None
            self.orders[o["id"]] = o
            return o

        def _cancel(self, o):
            try:
                self.cl.cancel(o["xid"], SYM)
            except Exception:
                pass
            self._poll(o)  # take any fill that happened before the cancel
            self.orders.pop(o["id"], None)

        def cancel_all(self):
            for o in list(self.orders.values()):
                self._cancel(o)
            try:
                for x in self.cl.open_orders():
                    self.cl.cancel(x["id"], SYM)
            except Exception:
                pass

        def replan(self, bid, ask):
            want = self.ladder.want(bid, ask, self.sma) if self.ladder.active else []
            keep = {}
            for w in want:
                cur = next((o for o in self.orders.values() if o["side"] == w["side"] and o["tag"] != "entry" and o["id"] not in keep), None)
                same = (cur and cur["c"] - cur["filled"] == w["c"] and abs(cur["price"] - w["price"]) <= 3 * B.TICK and
                        ((w["side"] == "sell" and cur.get("lot") == w.get("lot")) or
                         (w["side"] == "buy" and abs(cur.get("level", 0) - w.get("level", 0)) < 1e-6)))
                if same:
                    keep[cur["id"]] = cur
                    continue
                if cur:
                    self._cancel(cur)
                extra = {k: v for k, v in w.items() if k in ("lot", "level")}
                o = self.place(w["side"], w["price"], w["c"], w["tag"], **extra)
                if o:
                    keep[o["id"]] = o
            for o in list(self.orders.values()):
                if o["id"] not in keep and o["tag"] != "entry":
                    self._cancel(o)

        def entry_logic(self, bid, ask, now):
            ok = self.high4h is not None and bid >= self.ladder.entry_filter * self.high4h
            cur = next((o for o in self.orders.values() if o["tag"] == "entry"), None)
            if cur and (not ok or (now - cur["born"] >= 60 and cur["price"] != bid)):
                self._cancel(cur)
                cur = None
            if ok and not cur and not self.ladder.active:
                self.place("buy", bid, self.ladder.entry_c, "entry")

        def process_candles(self, now, bid, ask):
            pass  # fills come from the exchange

        def _poll(self, o):
            r = self.cl.order(o["xid"])
            new = r["filled"] - o["filled"]
            if new > 0:
                self._fill(o, new, r["avg"] or o["price"], r["fee"] * new / max(1, r["filled"]))
            if r["state"] in ("closed", "cancelled", "rejected") or r["filled"] >= o["c"]:
                self.orders.pop(o["id"], None)

        def _fill(self, o, n, px, fee):
            L = self.ladder
            o["filled"] += n
            if o["tag"] == "entry":
                if not L.active:
                    L.start_cycle(px, n)
                    o["lot"] = L.lots[-1]["id"]
                    self.log_trade("ENTRY", "buy", n, px, note="cycle start (live)", fee=fee)
                    self.n.send("LIVE %s cycle %d started: bought %d @ %.1f" % (self.live_key, L.cycle, n, px), "")
                else:
                    lot = next((l for l in L.lots if l["id"] == o.get("lot")), None)
                    if lot:
                        lot["c"] += n
                    self.log_trade("ENTRY", "buy", n, px, note="entry part fill", fee=fee)
            elif o["side"] == "buy":
                lot = next((l for l in L.lots if l["id"] == o.get("lot_new")), None)
                if lot:
                    lot["c"] += n
                else:
                    L.buy_fill(px, n, o["level"])
                    o["lot_new"] = L.lots[-1]["id"]
                self.log_trade("BUY", "buy", n, px, note="level %.1f (live)" % o["level"], fee=fee)
                self.n.send("LIVE %s BUY %d @ %.1f (holding %d)" % (self.live_key, n, px, L.held()), "", bulk=True)
            else:
                lot = next((l for l in L.lots if l["id"] == o.get("lot")), None)
                if lot is None:
                    raise Halt("sell fill for a lot the ladder no longer has")
                pnl = (px - lot["buy_price"]) * n * C
                lot["c"] -= n
                if lot["c"] <= 0:
                    L.lots.remove(lot)
                    if not L.lots:
                        L.active = False
                self.log_trade("SELL", "sell", n, px, pnl=pnl, note="lot bought @ %.1f (live)" % lot["buy_price"], fee=fee)
                self.n.send("LIVE %s SELL %d @ %.1f, gross %.3f USD (holding %d)" % (self.live_key, n, px, pnl, L.held()), "", bulk=True)
                if not L.active:
                    self.log_trade("CYCLE_END", "-", 0, px, note="all lots sold (live)")
                    self.n.send("LIVE %s cycle %d finished flat" % (self.live_key, L.cycle), "")

        def maybe_reports(self, now, mark):
            t = B.ist(now)
            day = t.strftime("%Y-%m-%d")
            if t.hour == 23 and t.minute >= 55 and self.last_summary_day != day:
                self.last_summary_day = day
                sells, pnl, fees = 0, 0.0, 0.0
                if os.path.exists(self.live_trades):
                    for r in csv.DictReader(open(self.live_trades)):
                        if r["time_ist"].startswith(day):
                            fees += float(r["fee_usd"])
                            if r["event"] == "SELL":
                                sells += 1
                                pnl += float(r["pnl_usd"])
                L = self.ladder
                self.n.send("LIVE %s daily summary %s" % (self.live_key, day),
                            "Sells %d | gross %.2f USD | fees %.2f USD | net %.2f USD\nCycle %d, holding %d contracts (%.3f BTC)\n"
                            "Calls: %s" % (sells, pnl, fees, pnl - fees, L.cycle, L.held(), L.held() * C, self.calls.status()))

        # ---- one pass
        def live_step(self):
            self.cfg = load_cfg()[self.live_key]
            now = time.time()
            if not self.cfg["armed"] or self.cfg.get("halt"):
                if self.orders:
                    self.cancel_all()
                    self.save()
                return
            if os.path.exists(B.STOPFILE):
                if not self.paused:
                    self.cancel_all()
                    self.paused = True
                    self.n.send("LIVE %s paused (Pause All)" % self.live_key, "Orders cancelled, BTC kept.")
                    self.save()
                return
            self.paused = False
            try:
                for o in list(self.orders.values()):
                    self._poll(o)
                if not self.reconcile():
                    self.save()
                    return
                bid, ask, mark = self.feed.ticker()
                self.refresh_indicators(now)
                if self.ladder.active:
                    self.replan(bid, ask)
                else:
                    for o in [o for o in self.orders.values() if o["tag"] != "entry"]:
                        self._cancel(o)  # leftover ladder orders of a finished cycle
                    self.entry_logic(bid, ask, now)
                if self.cfg.get("calls"):
                    self.calls.tick(self.ladder, self.feed, self.sma, now, bid, ask, mark)
                self.maybe_reports(now, mark)
            except Halt as h:
                self.halt(str(h))
            self.save()
    return LiveBot

def build(key, cfg, feed, notifier):
    import bot as B
    if key == "ladder":
        base = B.Bot
    else:
        import variants
        base = variants.make_vbot_class(B)
    return make_live_class(base, key)(client_for(cfg["acct"]), cfg, feed, notifier)

def run():
    import bot as B
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HOME, ".env"))
    os.makedirs(os.path.join(HOME, "logs"), exist_ok=True)
    log.setLevel(logging.INFO)
    h = RotatingFileHandler(os.path.join(HOME, "logs", "ladderlive.log"), maxBytes=2_000_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    B.MODE = "LIVE"
    feed, noti = B.Feed(), B.Notifier()
    bots, errs, beat = {}, {}, 0
    log.info("ladder live runner started")
    while True:
        cfg = load_cfg()
        for k in KEYS:
            c = cfg[k]
            if c["armed"] and k not in bots:
                try:
                    bots[k] = build(k, c, feed, noti)
                    bots[k].reconcile(force=True)
                    noti.send("LIVE %s armed" % k, "Ladder %s now trades with real money on Delta account %s." % (k, c["acct"]))
                except Exception as e:
                    log.exception("cannot start %s: %s", k, e)
                    noti.send("LIVE %s could not start" % k, str(e))
                    put(k, armed=False)
                    continue
            if k in bots:
                try:
                    bots[k].live_step()
                    errs[k] = 0
                except Exception as e:
                    errs[k] = errs.get(k, 0) + 1
                    log.exception("%s step failed (%d): %s", k, errs[k], e)
                    if errs[k] == 5:
                        noti.send("LIVE %s ERROR" % k, "5 failures in a row: %s" % e)
                if not cfg[k]["armed"] and not bots[k].orders:
                    bots.pop(k)
        if time.time() - beat > 600:
            beat = time.time()
            log.info("beat | " + " | ".join("%s armed=%s halt=%s" % (k, cfg[k]["armed"], bool(cfg[k]["halt"])) for k in KEYS))
        time.sleep(3 if bots else 10)

def main():
    a = sys.argv[1:]
    key = next((x for x in a if x in KEYS), None)
    if "--status" in a:
        for k, c in load_cfg().items():
            st = {}
            try:
                st = json.load(open(os.path.join(HOME, "state", "live_%s_state.json" % k)))["ladder"]
            except Exception:
                pass
            print("%-7s armed=%-5s acct=%-9s calls=%s halt=%s | cycle %s, lots %d" % (
                k, c["armed"], c["acct"], c["calls"], c["halt"], st.get("cycle", 0), len(st.get("lots", []))))
        return
    if not key:
        if not a:
            return run()
        print(__doc__)
        return
    if "--arm" in a:
        acct = a[a.index("--acct") + 1] if "--acct" in a else load_cfg()[key]["acct"]
        print(put(key, armed=True, acct=acct, halt=None))
    elif "--disarm" in a:
        print(put(key, armed=False))
    elif "--clear-halt" in a:
        print(put(key, halt=None))
    elif "--calls-off" in a:
        print(put(key, calls=False))
    elif "--calls-on" in a:
        print(put(key, calls=True))
    elif "--check" in a:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HOME, ".env"))
        cl = client_for(load_cfg()[key]["acct"])
        print("account:", cl.profile())
        print("balances:", cl.balance())
        print("positions:", cl.positions())
        print("open BTCUSD orders:", len(cl.open_orders()))
        print("ticker:", cl.ticker(SYM))
    elif "--selftest" in a:
        if "--yes" not in a:
            print("add --yes to place one real 1-contract post-only buy 5% below the bid (then cancelled)")
            return
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HOME, ".env"))
        cl = client_for(load_cfg()[key]["acct"])
        t = cl.ticker(SYM)
        px = math.floor(t["bid"] * 0.95 / t["tick"]) * t["tick"]
        r = cl.place(SYM, "buy", 1, px, False, "Lselftest%d" % int(time.time()), post_only=True)
        print("placed:", r)
        time.sleep(3)
        print("status:", cl.order(r["id"]))
        cl.cancel(r["id"], SYM)
        time.sleep(2)
        print("after cancel:", cl.order(r["id"]), "| positions:", cl.positions())
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
