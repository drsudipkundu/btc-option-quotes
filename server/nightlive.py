"""LIVE night option sell on the server (31-Oct-2026). Rules = v4A-CG-SL (nightlogic, slope-half). Real orders on ONE Delta
sub-account, only when ARMED (state/night_live_cfg.json armed=true, written by `nightlive.py --arm ACCT BASE` after Sudip's yes).

"Smart seller" (Sudip's fish-market rules, claude/night-smart-seller-execution-design-2026-10-31.md):
 SELL : walk-away price = 80% of the bid at the start (never below $10). 1) polite offer at the mid for 60 s;
        2) sell into the bids down to the walk-away price; 3) wait 3 min and retry, 3 retries;
        4) up to 4 strikes further out (bid >= $10, same 80% rule); 5) stop, keep what is sold, skip the rest.
 INSURANCE BUY (crash guard): pay up to 2x the ask at the start, 5 tries; then up to 4 strikes further out; never gives up
        (tried again next tick).
 BUY-BACK 90%: buy up to 1.5x the ask (reduce-only); if not filled the leg stays open for the next try / 17:20 exit.
 17:20 EXIT: buy up to 3x the ask (reduce-only), retried every tick until expiry; Delta settles anything left at 17:30.
Safety: guard size limits (state/limits.json) on every opening order; after every order and every minute the real
positions on the account are compared with the bot's own record - any mismatch HALTS new sales and emails.
Control: page card "nlive" (Pause = no new sales, Exit = buy back everything), STOP file, `--disarm`.
"""
import os, sys, json, time, math, logging, datetime as dt
from logging.handlers import RotatingFileHandler

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
import nightlogic as NL
from nightlogic import Night, find, fee, is_full, next_expiry_ts, indicators, IST, MIN_BID

SID = "nlive"
CFG_F = os.path.join(HOME, "state", "night_live_cfg.json")
STOPF = os.path.join(HOME, "STOP")
C = 0.001 # BTC per contract
OPT = ("C-BTC", "P-BTC")
DEF = dict(armed=False, acct="serverbot", base=0.02, client="live", walk=0.8, polite_s=60, retries=3, retry_wait_s=180,
           further=4, ins_cap=2.0, ins_tries=5, bb_cap=1.5, ue_cap=3.0, fill_wait_s=6)
log = logging.getLogger("nlive")

def cfg():
    v = dict(DEF)
    try:
        v.update(json.load(open(CFG_F)))
    except Exception:
        pass
    return v

def put_cfg(**kw):
    v = cfg()
    v.update(kw)
    os.makedirs(os.path.dirname(CFG_F), exist_ok=True)
    json.dump(v, open(CFG_F + ".tmp", "w"))
    os.replace(CFG_F + ".tmp", CFG_F)
    return v

def tick_round(p, tick, up):
    n = p / tick
    return round((math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)) * tick, 8)

class LiveNight(Night):
    """Night rules of v4A-CG-SL; fills come from real orders."""

    def __init__(self, client, base, notify, logf, sleep=time.sleep, now_fn=None):
        Night.__init__(self, "v4asl", base, HOME, notify=notify, log=logf)
        self.lab = "NLIVE V4ASL"
        self.state_path = os.path.join(HOME, "state", "night_%s.json" % SID)
        self.csv_path = os.path.join(HOME, "logs", "trades_night_%s.csv" % SID)
        self.S = dict(night=None, exp=0, legs=[], fired=[], picks={}, cg={"PE": {}, "CE": {}}, next_id=1,
                      total_pnl=0.0, nights=0, window_closed=None, halt=None)
        self.load()
        self.S.setdefault("halt", None)
        self.cl, self.sleep, self.now_fn = client, sleep, now_fn or (lambda: dt.datetime.now(IST))
        self.ch = []
        self.cfg = cfg()

    # ------------------------------------------------ exchange helpers
    def book(self, sym):
        try:
            r = self.cl._http("GET", "/v2/l2orderbook/%s" % sym, {"depth": 20})["result"]
            bids = [(float(x["price"]), int(x["size"])) for x in (r.get("buy") or [])]
            asks = [(float(x["price"]), int(x["size"])) for x in (r.get("sell") or [])]
        except Exception:
            t = self.cl.ticker(sym)
            bids = [(t["bid"], 10 ** 6)] if t["bid"] > 0 else []
            asks = [(t["ask"], 10 ** 6)] if t["ask"] > 0 else []
        return sorted(bids, key=lambda x: -x[0]), sorted(asks, key=lambda x: x[0])

    def real_positions(self):
        return {k: v for k, v in self.cl.positions().items() if str(k).startswith(OPT)}

    def check_books(self, where):
        import guard
        try:
            diffs = guard.reconcile(self.real_positions(), guard.expected_positions([self]))
        except Exception as e:
            self.log("position read failed (%s): %s" % (where, e))
            return True
        if diffs and not self.S.get("halt"):
            self.S["halt"] = "%s: %s" % (where, "; ".join("%s Delta %s vs bot %s" % d for d in diffs))
            self.save()
            self.notify("LIVE HALTED - position mismatch", self.S["halt"] + "\nNo new sales until fixed. Closing orders still run.")
        return not diffs

    def _order(self, sym, side, n, price, reduce_only, wait_s):
        """one limit order, wait, cancel the rest. returns (filled contracts, avg price, fee)"""
        import guard
        if not reduce_only:
            guard.check_order(sym, side, n * C, False, self.cl.positions())
        cid = "nl%d%s" % (int(time.time() * 10) % 10 ** 10, side[0])
        o = self.cl.place(sym, side, int(n), price, reduce_only, cid)
        t_end = time.time() + wait_s
        while o["filled"] < n and o["state"] not in ("cancelled", "rejected", "closed") and time.time() < t_end:
            self.sleep(1)
            o = self.cl.order(o["id"])
        if o["filled"] < n and o["state"] not in ("cancelled", "rejected", "closed"):
            try:
                self.cl.cancel(o["id"], sym)
            except Exception:
                pass
            o = self.cl.order(o["id"])
        return o["filled"], o["avg"], o["fee"]

    def _sweep(self, sym, side, n, limit_px, reduce_only, wait_s):
        """take what the book offers up to limit_px (sell: bids >= limit, buy: asks <= limit)"""
        bids, asks = self.book(sym)
        lv = [x for x in (bids if side == "sell" else asks) if (x[0] >= limit_px - 1e-9 if side == "sell" else x[0] <= limit_px + 1e-9)]
        if not lv:
            return 0, 0.0, 0.0
        avail = sum(s for _, s in lv)
        q = min(n, avail)
        px = lv[-1][0] # worst acceptable visible level; the exchange fills better levels first
        return self._order(sym, side, q, px, reduce_only, self.cfg["fill_wait_s"])

    # ------------------------------------------------ smart sell / buy
    def sell_smart(self, o0, want, side_typ):
        P, fills, left = self.cfg, [], want
        cands = [o0] + self.further(o0, side_typ, P["further"])
        for i, o in enumerate(cands):
            if left <= 0:
                break
            t = self.cl.ticker(o["sym"])
            ref = t["bid"]
            if ref < MIN_BID:
                continue
            walk = max(MIN_BID, tick_round(ref * P["walk"], t["tick"] or 0.5, True))
            if i == 0 and t["ask"] > ref:
                mid = tick_round((ref + t["ask"]) / 2, t["tick"] or 0.5, True)
                if mid > ref:
                    f, a, fe = self._order(o["sym"], "sell", left, mid, False, P["polite_s"])
                    if f:
                        fills.append((o, f, a, fe))
                        left -= f
            rounds = (P["retries"] + 1) if i == 0 else 1
            for r in range(rounds):
                if left <= 0:
                    break
                f, a, fe = self._sweep(o["sym"], "sell", left, walk, False, P["fill_wait_s"])
                if f:
                    fills.append((o, f, a, fe))
                    left -= f
                if left > 0 and r < rounds - 1:
                    if self.now_fn().hour * 100 + self.now_fn().minute >= 2355:
                        break
                    self.sleep(P["retry_wait_s"])
        if left > 0:
            self.notify("%s sold %d of %d contracts - rest skipped" % (self.lab, want - left, want),
                        "walk-away price / thin book; tried %d strike(s)" % len(cands))
        return fills

    def further(self, o0, typ, k):
        if not self.ch:
            return []
        same = [o for o in self.ch if o["typ"] == typ and not is_full(o, self.S.get("full", []))]
        if typ == "CE":
            out = sorted([o for o in same if o["strike"] > o0["strike"]], key=lambda o: o["strike"])
        else:
            out = sorted([o for o in same if o["strike"] < o0["strike"]], key=lambda o: -o["strike"])
        return out[:k]

    def buy_insurance(self, o0, want, typ):
        P = self.cfg
        for o in [o0] + self.further(o0, typ, P["further"]):
            t = self.cl.ticker(o["sym"])
            if t["ask"] <= 0:
                continue
            cap = tick_round(t["ask"] * P["ins_cap"], t["tick"] or 0.5, False)
            fills, left = [], want
            for _ in range(P["ins_tries"]):
                f, a, fe = self._sweep(o["sym"], "buy", left, cap, False, P["fill_wait_s"])
                if f:
                    fills.append((o, f, a, fe))
                    left -= f
                if left <= 0:
                    return fills
                self.sleep(5)
            if fills:
                return fills
        return []

    # ------------------------------------------------ Night hooks
    def _open(self, now, spot, key, kind, side, o, qty, direction, ex_note=""):
        want = int(round(qty / C))
        if want <= 0:
            return None
        if direction == "S" and (self.S.get("halt") or not self.cfg.get("armed")):
            return None
        try:
            fills = self.sell_smart(o, want, side) if direction == "S" else self.buy_insurance(o, want, side)
        except Exception as e:
            self.notify("%s order error" % self.lab, "%s %s %s: %s" % ("sell" if direction == "S" else "buy", o["sym"], want, e))
            self.check_books("after error")
            return None
        first = None
        for oo, f, avg, fe in fills:
            leg = dict(id=self.S["next_id"], set=key, kind=kind, side=side, sym=oo["sym"], strike=oo["strike"],
                       qty=round(f * C, 3), dir=direction, entry=avg, t=now.isoformat(), closed=False, exit=None, fee=fe)
            self.S["next_id"] += 1
            self.S["legs"].append(leg)
            self.row(now, "SELL" if direction == "S" else "BUY", leg, avg, fe, 0.0, ex_note or "live")
            self.notify("%s %s %s %d contracts @ %.1f" % (self.lab, "SOLD" if direction == "S" else "BOUGHT", oo["sym"], f, avg),
                        "set=%s kind=%s spot=%.1f fee=%.4f" % (key, kind, spot, fe))
            first = first or leg
        self.save()
        self.check_books("after %s" % ("sale" if direction == "S" else "insurance"))
        return first

    def _close(self, now, spot, leg, o, why):
        """real closing order; returns pnl of the part closed, or None if nothing filled (leg stays open)"""
        n = int(round(leg["qty"] / C))
        cap_mult = self.cfg["ue_cap"] if why in ("UE", "STOP") else self.cfg["bb_cap"]
        t = self.cl.ticker(leg["sym"])
        if leg["dir"] == "S":
            if t["ask"] <= 0:
                return None
            f, avg, fe = self._sweep(leg["sym"], "buy", n, tick_round(t["ask"] * cap_mult, t["tick"] or 0.5, False), True, self.cfg["fill_wait_s"])
        else:
            if t["bid"] <= 0:
                return None
            f, avg, fe = self._sweep(leg["sym"], "sell", n, t["tick"] or 0.5, True, self.cfg["fill_wait_s"])
        if not f:
            return None
        part = f * C
        share = part / leg["qty"]
        pnl = ((leg["entry"] - avg) if leg["dir"] == "S" else (avg - leg["entry"])) * part - leg["fee"] * share - fe
        self.S["total_pnl"] += pnl
        if f >= n:
            leg["closed"], leg["exit"], leg["pnl"] = True, avg, pnl + leg.get("pnl_part", 0.0)
        else:
            leg["qty"] = round(leg["qty"] - part, 3)
            leg["fee"] -= leg["fee"] * share
            leg["pnl_part"] = leg.get("pnl_part", 0.0) + pnl
        self.row(now, "EXIT-" + why, dict(leg, qty=round(part, 3)), avg, fe, pnl, "live %s" % ("buy back" if leg["dir"] == "S" else "sell insurance"))
        self.notify("%s closed %s %d contracts @ %.1f (%s)" % (self.lab, leg["sym"], f, avg, why), "pnl %.2f USD" % pnl)
        self.save()
        self.check_books("after close")
        return pnl

    def _close_all(self, now, spot, ch, why, done_note):
        for l in sorted(self.open_legs(), key=lambda x: 0 if x["dir"] == "S" else 1):
            try:
                self._close(now, spot, l, None, why)
            except Exception as e:
                self.notify("%s close error" % self.lab, "%s: %s" % (l["sym"], e))
        if not self.open_legs():
            self._finish(now, done_note)
            return True
        return False

    def _universal_exit(self, now, spot, ch):
        return self._close_all(now, spot, ch, "UE", "17:20 exit")

    def squareoff(self, now, spot, ch):
        return self._close_all(now, spot, ch, "STOP", "stopped by you")

    def step(self, now, spot, ch, ind, stopped=False):
        self.cfg = cfg()
        self.ch = ch
        hm = now.hour * 100 + now.minute
        today = now.strftime("%Y-%m-%d")
        if self.open_legs() and now.timestamp() > self.S["exp"] + 600:
            self._settle(now, spot) # Delta has cash-settled whatever was left at 17:30
            return True
        if self.open_legs() and self.S["night"] and today > self.S["night"] and hm >= 1720:
            return self._universal_exit(now, spot, ch)
        if self.open_legs() and self.S["exp"]:
            ch = [o for o in ch if o["exp"] == self.S["exp"]]
        if not ch:
            return False
        changed = False
        if hm < 2330:
            for l in self.open_legs():
                if l["dir"] == "S":
                    o = find(ch, l["side"], l["strike"])
                    if o and o["mark"] > 0 and o["mark"] <= 0.1 * l["entry"]:
                        changed |= self._close(now, spot, l, o, "90PCT") is not None
            if self.S["night"] and not self.open_legs() and self.S["legs"] and not self.S.get("finished"):
                self._finish(now, "closed early (90%)")
                return True
        if 2330 <= hm <= 2358 and ind and not stopped and not self.S.get("halt"):
            changed |= self._entries(now, spot, ch, ind, today)
        if (hm >= 2330 or hm < 1715) and self.open_legs() and ind:
            changed |= self._crash_guard(now, spot, ch, ind)
        if changed:
            self.save()
        return changed

    def _finish(self, now, why):
        Night._finish(self, now, why)
        self.S["finished"] = self.S.get("night")
        self.save()

    def _entries(self, now, spot, ch, ind, today):
        """same as Night._entries; the boost check counts every piece of a split sale (several strikes)"""
        S = self.S
        if S["night"] != today:
            if self.open_legs():
                return False
            S.update(night=today, fired=[], picks={}, cg={"PE": {}, "CE": {}}, full=[], jump_told=[], finished=None, plan={})
            S["exp"] = min([o["exp"] for o in ch if o["exp"] > now.timestamp()], default=0)
        if S["exp"]:
            ch = [o for o in ch if o["exp"] == S["exp"]]
        if ind["hv14"] is None or ind["hv7"] is None:
            return False
        pk = NL.make_picks(spot, ind["hv14"], ch, S.get("full", []))
        S["picks"] = pk
        changed = False
        for p in self.plan(ind):
            tag = p["key"]
            if tag in S["fired"]:
                continue
            strike = pk["%s_%s" % (p["side"].lower(), p["pk"])]
            if strike in (0, 9999999):
                continue
            o = find(ch, p["side"], strike)
            if not o or o["bid"] < MIN_BID or self.net_short(p["side"]) > 1e-9:
                continue
            S["fired"].append(tag) # one attempt per night per set, filled or not
            S.setdefault("plan", {})[tag] = round(p["qty"], 3)
            changed = True
            self._open(now, spot, tag, p["kind"], p["side"], o, round(p["qty"], 3), "S")
        bq = self.boost_qty(ind)
        if bq and "boost" not in S["fired"]:
            t = [l for l in self.open_legs() if l["set"] == "trend" and l["kind"] == "main" and l["dir"] == "S"]
            if t:
                m = t[0]
                o = find(ch, m["side"], m["strike"])
                planned = (S.get("plan") or {}).get("trend", m["qty"])
                if o and o["iv"] * 100 >= 140 * ind["hv7"] and abs(self.net_short(m["side"])) < 1.2 * planned:
                    S["fired"].append("boost")
                    changed = True
                    self._open(now, spot, "boost", "boost", m["side"], o, round(bq, 3), "S")
        return changed

# ---------------------------------------------------------------- service
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", nargs=2, metavar=("ACCT", "BASE"))
    ap.add_argument("--disarm", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--clear-halt", action="store_true")
    ap.add_argument("--client", choices=("live", "paper"))
    a = ap.parse_args()
    if a.arm:
        v = put_cfg(armed=True, acct=a.arm[0].lower(), base=float(a.arm[1]), client=a.client or cfg()["client"])
        print("ARMED:", v); return
    if a.disarm:
        print("DISARMED:", put_cfg(armed=False)); return
    if a.client:
        print("client:", put_cfg(client=a.client)); return
    if a.clear_halt:
        p = os.path.join(HOME, "state", "night_%s.json" % SID)
        d = json.load(open(p)); d["halt"] = None
        json.dump(d, open(p + ".tmp", "w")); os.replace(p + ".tmp", p)
        print("halt cleared (restart the service: sudo systemctl restart nightlive)"); return
    if a.status:
        v = cfg(); print("cfg:", v)
        try:
            print("state:", json.load(open(os.path.join(HOME, "state", "night_%s.json" % SID))))
        except Exception:
            print("state: none yet")
        return
    os.makedirs(os.path.join(HOME, "logs"), exist_ok=True)
    log.setLevel(logging.INFO)
    h = RotatingFileHandler(os.path.join(HOME, "logs", "nightlive.log"), maxBytes=2_000_000, backupCount=5)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HOME, ".env"))
    import bot as B, control, liveorders as LO, nightbot as NB
    B.MODE = "LIVE"
    nf = B.Notifier()

    def notify(s, b=""):
        log.info("%s | %s", s, b.replace("\n", " | "))
        nf.send("NIGHT " + s, b)
    c0 = cfg()
    client = LO.Paper() if c0["client"] == "paper" else LO.Live(c0["acct"])
    n = LiveNight(client, c0["base"], notify, log.info)
    feed = NB.Feed()
    notify("%s service started" % n.lab, "account %s, base %.3f BTC, client %s, armed %s" % (c0["acct"], c0["base"], c0["client"], c0["armed"]))
    n.check_books("start")
    ind, ind_t, last_chk, fails = None, 0, 0, 0
    while True:
        try:
            now_ts = time.time()
            now = dt.datetime.fromtimestamp(now_ts, IST)
            hm = now.hour * 100 + now.minute
            in_window = 2315 <= hm <= 2358
            ctl = control.get(SID)
            if not (in_window or n.open_legs()):
                wait = 30
            else:
                spot = feed.spot()
                if not ind or now_ts - ind_t >= (60 if in_window else 900):
                    ind, ind_t = indicators(feed.candles(now_ts), now_ts), now_ts
                exp_ts = (n.S["exp"] if n.open_legs() and n.S["exp"] else 0) or next_expiry_ts(now_ts)
                ch = feed.chain(exp_ts)
                n.cfg = cfg()
                if ctl["state"] == "stopped" and n.open_legs():
                    n.squareoff(now, spot, ch)
                else:
                    n.step(now, spot, ch, ind, os.path.exists(STOPF) or ctl["state"] != "running" or not cfg()["armed"])
                wait = 5 if in_window else 20
            if n.open_legs() and time.time() - last_chk > 60:
                last_chk = time.time()
                n.check_books("minute check")
            fails = 0
        except Exception as e:
            fails += 1
            log.exception("tick failed (%d): %s", fails, e)
            if fails == 5:
                notify("%s ERROR" % n.lab, "5 failures in a row: %s" % e)
            wait = min(60, 5 * fails)
        time.sleep(wait)

if __name__ == "__main__":
    main()
