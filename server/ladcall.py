"""Ladder CE leg (1-Nov-2026): the v9 CALL v3 call rules (Tradetron template 999071810) for the server ladders,
every call SALE done by Smart Sell (ssjob.py). Paper by default; the same class runs live (ladderlive.py).

Rules (as live v9 CALL v3 after 21-Oct-2026):
 COVERED CALL  from 17:35 IST (till midnight) when no call is open: strike = next-day CE with delta nearest 0.03,
               only if strike > BTC x 1.05; qty = contracts of held lots whose sell target >= strike (min 1).
 EXTRA CALL    17:35-17:50, only if yesterday's daily close <= SMA100: qty = min(2 x covered sold, 0.3 BTC), same strike.
 EXTRA STOPS   BTC >= strike x 1.05 -> buy back the extra (stop 1). (The x1.06 hard stop of Tradetron exists for missed
               ticks; here stop 1 is checked every tick and retried until done, so it covers that case.)
 NO-NAKED      every tick: covered calls open above the lots still covered -> buy back the excess (lot by lot).
 17:20-17:30   on expiry day: buy back everything still open.
 EXPIRY        anything still open after 17:30 (bot was down) settles at intrinsic value (paper) / is left to Delta (live).
Sale retries: if a sale could not start or sold nothing, it is tried again every 30 min until midnight (max 3 tries)."""
import os, json, csv, time, datetime as dt
import ssjob
from nightlogic import fee as opt_fee, next_expiry_ts, OI_CAP_USD, OI_FULL_FRAC

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UTC = dt.timezone.utc
C = 0.001
CP = dict(delta=0.03, min_otm=1.05, xmul=2.0, xmax_btc=0.3, stop1=1.05, sale_from=1735, x_until=1750,
          bb_from=1720, floor=1.0, retry_s=1800, max_tries=3, bb_cap=1.5, stop_cap=3.0, ue_cap=3.0)
COLS = ["time_ist", "mode", "event", "kind", "symbol", "strike", "contracts", "price", "fee_usd", "pnl_usd", "note"]

def chain_with_delta(exp_ts, public=None):
    """next-expiry BTC calls with bid/ask/mark/delta. public(path, params) -> json (delta_api.public by default)."""
    if public is None:
        import delta_api
        public = delta_api.public
    date = dt.datetime.fromtimestamp(exp_ts, UTC).strftime("%d-%m-%Y")
    res = public("/v2/tickers", {"contract_types": "call_options", "underlying_asset_symbols": "BTC", "expiry_date": date})["result"]
    out = []
    f = lambda x: float(x) if x not in (None, "") else 0.0
    for t in res:
        p = str(t.get("symbol", "")).split("-")
        if len(p) != 4 or p[0] != "C":
            continue
        q, g = t.get("quotes") or {}, t.get("greeks") or {}
        out.append(dict(sym=t["symbol"], typ="CE", strike=float(p[2]), exp=exp_ts, bid=f(q.get("best_bid")),
                        ask=f(q.get("best_ask")), mark=f(t.get("mark_price")), delta=f(g.get("delta")),
                        ro=bool(t.get("oi_reduce_only_mode")) or f(t.get("oi_value_usd")) >= OI_CAP_USD * OI_FULL_FRAC))
    return out

class CallLeg:
    def __init__(self, key, notify=None, log=None, mode="paper", ex=None, home=HOME, public=None, params=None):
        self.key, self.mode, self.home = key, mode, home
        self.notify = notify or (lambda s, b="": None)
        self.log = log or (lambda *a: None)
        self.ex = ex or ssjob.PaperExec()
        self.public = public
        self.P = dict(CP, **(params or {}))
        tag = key if mode == "paper" else "live_" + key
        self.state_f = os.path.join(home, "state", "calls_%s.json" % tag)
        self.csv_f = os.path.join(home, "logs", "calls_%s.csv" % tag)
        self.S = dict(pos=[], job=None, tries={}, last_try=0, total_pnl=0.0, day_close=None, day_close_t=0,
                      x_done_day=None, sold_day=None)
        try:
            self.S.update(json.load(open(self.state_f)))
        except Exception:
            pass
        self._ch, self._ch_t = [], 0

    # ---------------------------------------------------------------- bookkeeping
    def save(self):
        os.makedirs(os.path.dirname(self.state_f), exist_ok=True)
        json.dump(self.S, open(self.state_f + ".tmp", "w"))
        os.replace(self.state_f + ".tmp", self.state_f)

    def row(self, now, event, kind, sym, k, c, price, f, pnl, note=""):
        os.makedirs(os.path.dirname(self.csv_f), exist_ok=True)
        new = not os.path.exists(self.csv_f)
        with open(self.csv_f, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(COLS)
            w.writerow([now.strftime("%Y-%m-%d %H:%M:%S"), self.mode.upper(), event, kind, sym, k, c, round(price, 2),
                        round(f or 0, 4), round(pnl, 4), note])

    def open_c(self, kind=None):
        return sum(p["c"] for p in self.S["pos"] if kind is None or p["kind"] == kind)

    def pending(self):
        return bool(self.S["job"]) or bool(self.S["pos"])

    def expected_positions(self):
        out = {}
        for p in self.S["pos"]:
            out[p["sym"]] = out.get(p["sym"], 0) - p["c"]
        return {k: v for k, v in out.items() if v}

    # ---------------------------------------------------------------- market data
    def chain(self, exp_ts, ts, every=20):
        if not self._ch or ts - self._ch_t >= every or (self._ch and self._ch[0]["exp"] != exp_ts):
            self._ch, self._ch_t = chain_with_delta(exp_ts, self.public), ts
        return self._ch

    def prev_close(self, feed, ts):
        if self.S.get("day_close") is None or ts - self.S.get("day_close_t", 0) > 3600:
            day0 = int(ts // 86400) * 86400
            cd = [x for x in feed.candles("1d", day0 - 5 * 86400, ts) if x["time"] < day0]
            if cd:
                self.S["day_close"], self.S["day_close_t"] = float(cd[-1]["close"]), ts
        return self.S.get("day_close")

    @staticmethod
    def covered(ladder, k):
        if not ladder.active:
            return 0
        return sum(l["c"] for l in ladder.lots if ladder.sell_price(l) >= k - 1e-9)

    # ---------------------------------------------------------------- buys (closing)
    def _buy_back(self, now, spot, p, n, why, cap):
        o = next((x for x in self._ch if x["sym"] == p["sym"]), None) or dict(sym=p["sym"], ask=0, mark=0, strike=p["k"])
        fills = self.ex.buy(o, int(n), cap)
        got = 0
        for q, px, fe in fills:
            if q <= 0:
                continue
            q = min(q, p["c"])
            f_out = fe if fe is not None else opt_fee(spot, px, q * C)
            share = q / p["c"]
            f_in = p["fee"] * share
            pnl = (p["entry"] - px) * q * C - f_in - f_out
            p["fee"] -= f_in
            p["c"] -= q
            got += q
            self.S["total_pnl"] += pnl
            self.row(now, "BUYBACK-" + why, p["kind"], p["sym"], p["k"], q, px, f_out, pnl,
                     "sold @ %.1f" % p["entry"])
            self.notify("%s call %s: bought back %d %s @ %.1f" % (self.key, why, q, p["sym"], px), "P&L %.2f USD" % pnl)
        self.S["pos"] = [x for x in self.S["pos"] if x["c"] > 0]
        return got

    def _settle(self, now, spot):
        for p in self.S["pos"]:
            intr = max(0.0, spot - p["k"])
            pnl = (p["entry"] - intr) * p["c"] * C - p["fee"]
            self.S["total_pnl"] += pnl
            self.row(now, "SETTLE", p["kind"], p["sym"], p["k"], p["c"], intr, 0, pnl, "expired while open (settled at intrinsic)")
        self.S["pos"] = []

    # ---------------------------------------------------------------- one tick
    def tick(self, ladder, feed, sma, now_ts, bid, ask, mark):
        now = dt.datetime.fromtimestamp(now_ts, IST)
        hm = now.hour * 100 + now.minute
        P, S = self.P, self.S
        changed = False
        # 1) positions: expiry / 17:20 buy-back / stops / no-naked
        if S["pos"]:
            exp = S["pos"][0]["exp"]
            ch = self.chain(exp, now_ts)
            if now_ts >= exp:
                if self.mode == "paper":
                    self._settle(now, mark)
                else:
                    self.notify("%s LIVE call expired while open" % self.key, "check the account - Delta settles it")
                    self.row(now, "EXPIRED", "-", "-", 0, self.open_c(), 0, 0, 0, "live: left to exchange settlement")
                    S["pos"] = []
                changed = True
            elif now_ts >= exp - 600 and hm >= P["bb_from"]:
                for p in list(S["pos"]):
                    self._buy_back(now, mark, p, p["c"], "1720", P["ue_cap"])
                changed = True
            else:
                for p in [x for x in S["pos"] if x["kind"] == "x"]:
                    if mark >= p["k"] * P["stop1"]:
                        self._buy_back(now, mark, p, p["c"], "STOP1", P["stop_cap"])
                        changed = True
                cov = sorted([x for x in S["pos"] if x["kind"] == "cov"], key=lambda x: x["k"])
                if cov:
                    still = self.covered(ladder, cov[0]["k"])
                    excess = self.open_c("cov") - still
                    for p in cov:
                        if excess <= 0:
                            break
                        n = min(excess, p["c"])
                        excess -= self._buy_back(now, mark, p, n, "LOT", P["bb_cap"]) or 0
                        changed = True
        # 2) a running Smart Sell job
        if S["job"]:
            J = S["job"]
            ch = self.chain(J["exp"], now_ts, every=5)
            if ssjob.run_job(J, ch, now_ts, self.ex):
                self._job_done(now, mark, J, ladder, feed, sma, now_ts, hm)
            changed = True
        # 3) start a new covered sale
        elif not S["pos"] and hm >= P["sale_from"] and ladder.active and ladder.lots:
            day = now.strftime("%Y-%m-%d")
            tries = S["tries"].get(day, 0)
            if S.get("sold_day") != day and tries < P["max_tries"] and now_ts - S.get("last_try", 0) >= P["retry_s"]:
                S["last_try"] = now_ts
                exp = next_expiry_ts(now_ts)
                ch = self.chain(exp, now_ts)
                cands = [o for o in ch if o["delta"] > 0 and not o["ro"]]
                if cands:
                    o = min(cands, key=lambda x: abs(x["delta"] - P["delta"]))
                    c = self.covered(ladder, o["strike"])
                    if o["strike"] > mark * P["min_otm"] and c >= 1:
                        S["tries"] = {day: tries + 1}
                        S["job"] = ssjob.new_job("cov", "CE", o, c, ch, now_ts, P["floor"], "covered; delta %.3f" % o["delta"])
                        self.log("%s call: covered sale started %s x%d" % (self.key, o["sym"], c))
                        if ssjob.run_job(S["job"], ch, now_ts, self.ex):
                            self._job_done(now, mark, S["job"], ladder, feed, sma, now_ts, hm)
                changed = True
        if changed:
            self.save()
        return changed

    def _job_done(self, now, spot, J, ladder, feed, sma, now_ts, hm):
        S, P = self.S, self.P
        S["job"] = None
        kind = "cov" if J["key"] == "cov" else "x"
        sold, main_k = 0, None
        by = {}
        for f in J["fills"]:
            a = by.setdefault(f["sym"], dict(sym=f["sym"], k=f["strike"], c=0, val=0.0, fee=0.0, ref=f["ref"], walk=f["walk"]))
            a["c"] += f["c"]
            a["val"] += f["c"] * f["price"]
            a["fee"] += f["fee"] if f["fee"] is not None else opt_fee(spot, f["price"], f["c"] * C)
        for a in by.values():
            avg = a["val"] / a["c"]
            S["pos"].append(dict(sym=a["sym"], k=a["k"], kind=kind, c=a["c"], entry=avg, fee=a["fee"], exp=J["exp"]))
            self.row(now, "SELL", kind, a["sym"], a["k"], a["c"], avg, a["fee"], 0.0,
                     "smart sell; start bid %.1f walk-away %.1f; %s" % (a["ref"], a["walk"], J["note"]))
            self.notify("%s call SOLD %d %s @ %.1f (%s, smart sell)" % (self.key, a["c"], a["sym"], avg, kind), J["note"])
            sold += a["c"]
            if main_k is None or a["c"] > by.get(main_k, {}).get("c", 0):
                main_k = a["sym"]
        if J["left"] > 0:
            self.row(now, "SKIP", kind, "", 0, J["left"], 0, 0, 0, "sold %d of %d (walk-away price / thin book)" % (J["want"] - J["left"], J["want"]))
        if kind == "cov" and sold:
            S["sold_day"] = now.strftime("%Y-%m-%d")
            pc = self.prev_close(feed, now_ts)
            if hm < P["x_until"] and sma and pc is not None and pc <= sma:
                xn = min(int(P["xmul"] * sold), int(round(P["xmax_btc"] / C)))
                ch = self.chain(J["exp"], now_ts, every=0)
                o = next((x for x in ch if x["sym"] == main_k), None)
                if o and xn >= 1:
                    S["job"] = ssjob.new_job("x", "CE", o, xn, ch, now_ts, P["floor"],
                                             "extra x%.0f (close %.0f <= SMA100 %.0f)" % (P["xmul"], pc, sma))
                    if ssjob.run_job(S["job"], ch, now_ts, self.ex):
                        self._job_done(now, spot, S["job"], ladder, feed, sma, now_ts, hm)

    # ---------------------------------------------------------------- stop button
    def close_all(self, now_ts, mark, why="STOP"):
        now = dt.datetime.fromtimestamp(now_ts, IST)
        if self.S["job"]:
            self.S["job"] = None
        if self.S["pos"]:
            self.chain(self.S["pos"][0]["exp"], now_ts, every=0)
            for p in list(self.S["pos"]):
                self._buy_back(now, mark, p, p["c"], why, self.P["ue_cap"])
        self.save()

    def status(self):
        S = self.S
        return dict(open=[(p["sym"], p["kind"], p["c"], round(p["entry"], 1)) for p in S["pos"]],
                    job=(S["job"] or {}).get("key"), total_pnl=round(S["total_pnl"], 2))

# ---------------------------------------------------------------- hook for the paper ladder bots
_LEGS = {}

def tick_for(bot_obj, key, now_ts, bid, ask, mark):
    """called at the end of every paper ladder step (bot.py / variants.py patch)."""
    leg = _LEGS.get(key)
    if leg is None:
        n = getattr(bot_obj, "n", None)
        leg = _LEGS[key] = CallLeg(key, notify=(lambda s, b="": n.send("CALL " + s, b, bulk=True)) if n else None)
    leg.tick(bot_obj.ladder, bot_obj.feed, bot_obj.sma, now_ts, bid, ask, mark)
    return leg

def squareoff_for(key, now_ts, mark):
    leg = _LEGS.get(key)
    if leg:
        leg.close_all(now_ts, mark)
