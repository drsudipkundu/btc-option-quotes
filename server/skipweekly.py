"""Skip-night weekly sell - PAPER (5-Nov-2026, Sudip: "Built it" after the full grid test,
project doc claude/skip-night-weekly-sell-full-grid-2026-11-05.md).

Rule (best balanced setting of the test):
  * On every night the v4A-CG-SL night sell does NOT sell its trend leg (quiet night, premium below $10, no usable strike),
  * at ~23:45 IST sell the SAME-SIDE (trend side: PUT if prev close > SMA50 else CALL) weekly option:
    the nearest Friday expiry at least 2 days away, strike 10% out of the money
    (PUT: highest listed strike <= spot x 0.90; CALL: lowest listed strike >= spot x 1.10; skip strikes Delta has capped),
  * only if the bid we can hit is at least $10 (if the strike has no bid, try up to 4 strikes further out),
  * size = the night base (NIGHT_BASE, 0.02 BTC), HALF when the MA50-slope acceleration > 0.123 (same slope rule as v4A-CG-SL;
    5-Nov slope test: same profit, worst open loss about halved); no take-profit, no stop: HELD TO EXPIRY (Friday 17:30 IST),
  * settled on the average BTC price of the last 30 minutes before expiry (as Delta settles), fees included.
Paper only: no real orders ever. State state/skipweekly.json, trades logs/trades_skipweekly.csv, log logs/skipweekly.log.
CLI: --status | --check (what it would sell right now, no state change)
"""
import os, sys, time, json, csv, logging, datetime as dt
from logging.handlers import RotatingFileHandler

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
import bot as B
import control
from nightlogic import Night, indicators, fee, is_full, IST, UTC, MIN_BID, SL_THR
from nightbot import Feed

DIST = 0.12          # 12% out of the money (Sudip chose option b, 5-Nov 17:58)
MIN_DAYS = 2         # weekly expiry at least 2 days after the 23:30 entry day
DECIDE_HM = 2345     # decide after the night copies (and Smart Sell retries) are done
LAST_HM = 2358
MAX_FURTHER = 4
LAB = "SKIP-WEEKLY 12%"
STATE_F = os.path.join(HOME, "state", "skipweekly.json")
CSV_F = os.path.join(HOME, "logs", "trades_skipweekly.csv")
COLS = ["time_ist", "night", "event", "reason", "side", "symbol", "strike", "expiry", "qty_btc", "price", "fee_usd", "pnl_usd", "note"]
log = logging.getLogger("skipweekly")

def setup_logging():
    os.makedirs(os.path.join(HOME, "logs"), exist_ok=True)
    log.setLevel(logging.INFO)
    fm = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (RotatingFileHandler(os.path.join(HOME, "logs", "skipweekly.log"), maxBytes=2_000_000, backupCount=3), logging.StreamHandler()):
        h.setFormatter(fm)
        log.addHandler(h)

def load():
    if os.path.exists(STATE_F):
        return json.load(open(STATE_F))
    return dict(night=None, pos=[], total_pnl=0.0, trades=0, wins=0, skips={}, last=None)

def save(S):
    os.makedirs(os.path.dirname(STATE_F), exist_ok=True)
    json.dump(S, open(STATE_F + ".tmp", "w"), indent=1)
    os.replace(STATE_F + ".tmp", STATE_F)

def row(now, night, event, reason="", p=None, price=0.0, f=0.0, pnl=0.0, note=""):
    os.makedirs(os.path.dirname(CSV_F), exist_ok=True)
    new = not os.path.exists(CSV_F)
    with open(CSV_F, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(COLS)
        w.writerow([now.strftime("%Y-%m-%d %H:%M:%S"), night or "", event, reason, p["side"] if p else "", p["sym"] if p else "",
                    p["strike"] if p else "", p["exp_ist"] if p else "", p["qty"] if p else "", round(price, 2), round(f, 4), round(pnl, 4), note])

def weekly_expiries(now_ts, n=3):
    """Next Friday 12:00 UTC expiries that are at least MIN_DAYS after today's (UTC) date at 12:00."""
    d = dt.datetime.fromtimestamp(now_ts, UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    first = d + dt.timedelta(days=MIN_DAYS)
    k = (4 - first.weekday()) % 7          # Friday = 4
    f = first + dt.timedelta(days=k)
    return [(f + dt.timedelta(days=7 * i)).timestamp() for i in range(n)]

def v4_sold_tonight(today):
    """Did the v4A-CG-SL paper copy sell its trend leg tonight? (None = cannot tell yet: Smart Sell still working)"""
    p = os.path.join(HOME, "state", "night_v4asl.json")
    if not os.path.exists(p):
        return False
    S = json.load(open(p))
    if S.get("night") != today:
        return False
    ss = S.get("ss") or {}
    if ss.get("night") == today and ss.get("jobs"):     # Smart Sell job still working on a sale
        return None
    return any(l.get("set") == "trend" and l.get("dir") == "S" for l in S.get("legs", []))

def choose(feed, now_ts, spot, side):
    """Return (option dict, expiry ts, note) or (None, None, reason)."""
    for exp in weekly_expiries(now_ts):
        ch = [o for o in feed.chain(exp) if o["typ"] == side]
        if not ch:
            continue
        ok = [o for o in ch if not is_full(o)]
        if side == "PE":
            tgt = spot * (1 - DIST)
            cands = sorted([o for o in ok if o["strike"] <= tgt], key=lambda o: -o["strike"])
        else:
            tgt = spot * (1 + DIST)
            cands = sorted([o for o in ok if o["strike"] >= tgt], key=lambda o: o["strike"])
        if not cands:
            return None, exp, "no listed strike 12%% out (target %.0f)" % tgt
        for o in cands[:1 + MAX_FURTHER]:
            if o["bid"] > 0:
                if o["bid"] < MIN_BID:
                    return None, exp, "bid %.1f below $10 floor (%s)" % (o["bid"], o["sym"])
                return o, exp, "target %.0f" % tgt
        return None, exp, "no bid on the 5 nearest strikes beyond %.0f" % tgt
    return None, None, "no weekly expiry listed"

class Runner:
    def __init__(self, feed, nf, base):
        self.feed, self.nf, self.base, self.S = feed, nf, base, load()
        self.last_mark, self.last_beat = 0, 0
        self.dummy = Night("v4asl", base, "/tmp/skipweekly_dummy")   # only for plan(): quiet-night check

    def send(self, subj, body=""):
        log.info("%s | %s", subj, body.replace("\n", " | "))
        try:
            self.nf.send("NIGHT " + subj, body)
        except Exception as e:
            log.warning("mail failed: %s", e)

    def tick(self, now_ts):
        S = self.S
        now = dt.datetime.fromtimestamp(now_ts, IST)
        hm, today = now.hour * 100 + now.minute, now.strftime("%Y-%m-%d")
        spot = None
        # ---- settlement: sample the price in the last 30 minutes, settle after expiry
        for p in [p for p in S["pos"] if not p.get("closed")]:
            if p["exp"] - 1800 <= now_ts < p["exp"]:
                spot = spot or self.feed.spot()
                p.setdefault("samples", []).append(spot)
                save(S)
            elif now_ts >= p["exp"] + 60:
                spot = spot or self.feed.spot()
                Se = sum(p["samples"]) / len(p["samples"]) if p.get("samples") else spot
                intr = max(0.0, p["strike"] - Se) if p["side"] == "PE" else max(0.0, Se - p["strike"])
                f2 = fee(Se, intr, p["qty"]) if intr > 0 else 0.0
                pnl = (p["entry"] - intr) * p["qty"] - p["fee"] - f2
                p.update(closed=True, exit=intr, settle_px=Se, pnl=pnl)
                S["total_pnl"] += pnl
                S["trades"] += 1
                S["wins"] += 1 if pnl > 0 else 0
                row(now, p["night"], "SETTLE", p["reason"], p, intr, f2, pnl, "settle price %.1f" % Se)
                self.send("%s settled %s: P&L %.2f USD" % (LAB, p["sym"], pnl),
                          "sold %.1f on %s, settle price %.1f, value at expiry %.1f | running total %.2f USD over %d trades (%d wins)" % (
                              p["entry"], p["night"], Se, intr, S["total_pnl"], S["trades"], S["wins"]))
                save(S)
        # ---- marks every 15 minutes (worst open loss)
        if now_ts - self.last_mark >= 900 and any(not p.get("closed") for p in S["pos"]):
            self.last_mark = now_ts
            chains = {}
            for p in [p for p in S["pos"] if not p.get("closed")]:
                try:
                    ch = chains.setdefault(p["exp"], self.feed.chain(p["exp"]))
                    o = next((o for o in ch if o["sym"] == p["sym"]), None)
                    if o and o["mark"] > 0:
                        p["mark"] = o["mark"]
                        p["worst"] = max(p.get("worst", 0.0), o["mark"])
                except Exception as e:
                    log.warning("mark failed: %s", e)
            save(S)
        # ---- tonight's decision
        if DECIDE_HM <= hm <= LAST_HM and S.get("night") != today:
            if os.path.exists(B.STOPFILE):
                return 30
            try:
                c4 = control.get("v4asl")
            except Exception:
                c4 = {"state": "running"}
            if c4.get("state", "running") != "running":     # v4A-CG-SL copy paused/stopped: it can't tell us tonight's skip
                S["last"] = dict(night=today, what="v4A-CG-SL paper copy not running - no decision")
                S["night"] = today
                save(S)
                return 30
            sold = v4_sold_tonight(today)
            if sold is None:
                return 15
            S["night"] = today
            if sold:
                S["last"] = dict(night=today, what="v4 sold its trend leg - nothing to do")
                save(S)
                log.info("%s: v4 sold tonight - no substitute", today)
                return 30
            ind = indicators(self.feed.candles(now_ts), now_ts)
            if not ind:
                S["last"] = dict(night=today, what="no indicators"); save(S)
                return 30
            spot = spot or self.feed.spot()
            reason = "quiet" if not self.dummy.plan(ind) else "floor/no strike"
            side = "PE" if ind["c1"] > ind["sma50"] else "CE"
            o, exp, note = choose(self.feed, now_ts, spot, side)
            S["skips"][reason] = S["skips"].get(reason, 0) + 1
            if not o:
                S["last"] = dict(night=today, what="skip night (%s) - no sale: %s" % (reason, note))
                row(now, today, "NO-SALE", reason, None, 0, 0, 0, note)
                self.send("%s: no sale tonight" % LAB, "v4 skipped (%s); %s %s" % (reason, side, note))
                save(S)
                return 30
            half = ind.get("sl_acc") is not None and ind["sl_acc"] > SL_THR   # slope rule (5-Nov test): half size when MA50 slope is speeding up
            q = round(self.base * (0.5 if half else 1.0), 3)
            p = dict(night=today, reason=reason, side=side, sym=o["sym"], strike=o["strike"], exp=exp,
                     exp_ist=dt.datetime.fromtimestamp(exp, IST).strftime("%d-%b %H:%M"), qty=q, entry=o["bid"],
                     fee=fee(spot, o["bid"], q), spot=spot, t=now.isoformat(), closed=False, mark=o["mark"], worst=o["mark"])
            S["pos"].append(p)
            S["last"] = dict(night=today, what="SOLD %s @ %.1f" % (o["sym"], o["bid"]))
            row(now, today, "SELL", reason, p, o["bid"], p["fee"], 0, note)
            self.send("%s SOLD %s %.3f BTC @ %.1f" % (LAB, o["sym"], q, o["bid"]),
                      "v4 skipped tonight (%s). Trend side %s, spot %.1f, %s; mark %.1f; held to expiry %s IST; slope accel %s -> %s size" % (
                          reason, side, spot, note, o["mark"], p["exp_ist"], ("%.3f" % ind["sl_acc"]) if ind.get("sl_acc") is not None else "n/a", "HALF" if half else "full"))
            save(S)
        if time.time() - self.last_beat > 600:
            self.last_beat = time.time()
            op = [p for p in S["pos"] if not p.get("closed")]
            log.info("beat open=%d total=%.2f trades=%d", len(op), S["total_pnl"], S["trades"])
        return 15 if (2340 <= hm <= 2359 or any(not p.get("closed") and p["exp"] - 1900 <= now_ts <= p["exp"] + 600 for p in S["pos"])) else 30

    def status(self):
        S = self.S
        out = ["%s (paper) | settled trades %d, wins %d, total P&L %.2f USD | skip nights seen %s" % (
            LAB, S["trades"], S["wins"], S["total_pnl"], S["skips"]), "last: %s" % S.get("last")]
        for p in S["pos"]:
            if not p.get("closed"):
                out.append(" open: %s %s %.3f BTC sold %.1f on %s, mark %.1f, worst mark %.1f, expires %s IST (%s)" % (
                    p["side"], p["sym"], p["qty"], p["entry"], p["night"], p.get("mark", 0), p.get("worst", 0), p["exp_ist"], p["reason"]))
        return "\n".join(out)

    def run_forever(self):
        self.send("%s paper started" % LAB, "Sells a weekly option 12%% out of the money (trend side) on nights the v4 night sell skips; held to expiry. Base %.3f BTC. Paper only." % self.base)
        fails = 0
        while True:
            try:
                wait = self.tick(time.time())
                fails = 0
            except Exception as e:
                fails += 1
                log.exception("tick failed (%d): %s", fails, e)
                if fails == 5:
                    self.send("%s ERROR" % LAB, "5 failures in a row: %s" % e)
                wait = min(60, 5 * fails)
            time.sleep(wait)

def main():
    setup_logging()
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HOME, ".env"))
    base = float(os.getenv("NIGHT_BASE", "0.02"))
    r = Runner(Feed(), B.Notifier(), base)
    if "--status" in sys.argv:
        print(r.status())
        return
    if "--check" in sys.argv:
        now = time.time()
        spot = r.feed.spot()
        ind = indicators(r.feed.candles(now), now)
        side = "PE" if ind["c1"] > ind["sma50"] else "CE"
        o, exp, note = choose(r.feed, now, spot, side)
        print("spot %.1f | trend side %s | quiet night: %s | weekly expiries %s" % (
            spot, side, not r.dummy.plan(ind), [dt.datetime.fromtimestamp(e, IST).strftime("%d-%b") for e in weekly_expiries(now)]))
        print("would sell:", (o["sym"], "bid", o["bid"], "mark", o["mark"]) if o else None, "|", note)
        print(r.status())
        return
    r.run_forever()

if __name__ == "__main__":
    main()
