#!/usr/bin/env python3
"""whatif - PAPER / REPORT ONLY (built 27-Nov-2026, Sudip 15:06 IST: "the trades I have closed manually, if not closed what would happen? do the changes for data capturing").
For every night that ended with 'stopped by you' (Telegram /exit and similar), it takes the legs that were closed BY HAND (EXIT-STOP rows, plus EXIT-CUT and EXIT-CUTHEDGE rows of /cut)
and, once the options have expired (17:30 IST), works out what holding them to expiry would have given:
  sold leg  : gain of holding = (exit price - intrinsic at expiry) x qty + exit fee saved
  far hedge : gain of holding = (intrinsic at expiry - exit price) x qty + exit fee saved
Settlement S = average of the last 30 one-minute closes of Delta BTCUSD before 17:30 IST (a stand-in for the expiry index, can differ by a few dollars).
It only sends public GET requests for candles. It NEVER places an order and changes nothing. Log: logs/whatif.csv (one row per leg, written once per leg after expiry).
  venv/bin/python whatif.py          run (cron 17:45 IST daily)
  venv/bin/python whatif.py --show   print only, no log
"""
import os, sys, csv, json, time, datetime as dt

H = os.path.expanduser(os.environ.get("BOT_HOME", "~/deltabot"))
LOGS = os.path.join(H, "logs")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
HAND = ("EXIT-STOP", "EXIT-CUT", "EXIT-CUTHEDGE")


def intrinsic(side, strike, S):
    return max(S - strike, 0.0) if side == "CE" else max(strike - S, 0.0)


def hold_gain(kind, exit_price, qty, intr, exit_fee):
    """kind 'sold' or 'hedge'; USD gain (+) or loss (-) of leaving the leg to expire instead of the hand exit"""
    g = (exit_price - intr) * qty if kind == "sold" else (intr - exit_price) * qty
    return g + exit_fee


def expiry_of(sym):
    """C-BTC-63000-271126 -> 2026-11-27 17:30 IST"""
    d = sym.split("-")[-1]
    return dt.datetime(2000 + int(d[4:6]), int(d[2:4]), int(d[0:2]), 17, 30, tzinfo=IST)


def settlement(expiry, get=None):
    """average of the last 30 one-minute closes before expiry; None if not available yet"""
    end = int(expiry.timestamp())
    if time.time() < end + 120:
        return None
    if get is None:
        import requests
        def get(u):
            return requests.get(u, timeout=20).json()
    j = get("https://api.india.delta.exchange/v2/history/candles?resolution=1m&symbol=BTCUSD&start=%d&end=%d" % (end - 1800, end))
    cs = sorted(j.get("result", j) if isinstance(j, dict) else j, key=lambda x: x["time"])
    cs = [c for c in cs if c["time"] < end]
    if len(cs) < 20:
        return None
    return sum(float(c["close"]) for c in cs[-30:]) / len(cs[-30:])


def legs_closed_by_hand(rows):
    ends = {r["night"] for r in rows if r["event"] == "NIGHT-END" and "stopped by you" in r.get("note", "")}
    cuts = {r["night"] for r in rows if r["event"] in ("EXIT-CUT", "EXIT-CUTHEDGE")}
    out = []
    for r in rows:
        if r["event"] in HAND and (r["night"] in ends or r["night"] in cuts):
            out.append(r)
    return out


def main():
    show = "--show" in sys.argv
    p = os.path.join(LOGS, "trades_night_nlive.csv")
    if not os.path.exists(p):
        print("no trade log yet"); return
    rows = list(csv.DictReader(open(p)))
    legs = legs_closed_by_hand(rows)
    out = os.path.join(LOGS, "whatif.csv")
    done = set()
    if os.path.exists(out):
        done = {(r["night"], r["time_ist"], r["symbol"]) for r in csv.DictReader(open(out))}
    new = []
    cache = {}
    for r in legs:
        key = (r["night"], r["time_ist"], r["symbol"])
        if key in done:
            continue
        exp = expiry_of(r["symbol"])
        if exp not in cache:
            try:
                cache[exp] = settlement(exp)
            except Exception as e:
                print("candles not read (%s): %s" % (type(e).__name__, e)); cache[exp] = None
        S = cache[exp]
        if S is None:
            print("%s %s: not expired yet or no candles" % (r["night"], r["symbol"])); continue
        strike = float(r["strike"]); qty = float(r["qty_btc"]); xp = float(r["price"]); fee = float(r["fee_usd"] or 0)
        kind = "hedge" if r["set"] == "wing" or r["event"] == "EXIT-CUTHEDGE" else "sold"
        it = intrinsic(r["side"], strike, S)
        g = hold_gain(kind, xp, qty, it, fee)
        new.append([r["night"], r["time_ist"], r["event"], kind, r["side"], r["symbol"], strike, qty, xp, fee, round(S, 1), round(it, 2), round(g, 4)])
        print("%s %s %s %s: S %.0f intrinsic %.2f, holding would have changed P&L by %+.2f USD" % (r["night"], kind, r["side"], r["symbol"], S, it, g))
    if show or not new:
        return
    os.makedirs(LOGS, exist_ok=True)
    isnew = not os.path.exists(out)
    with open(out, "a", newline="") as fh:
        w = csv.writer(fh)
        if isnew:
            w.writerow(["night", "time_ist", "event", "kind", "side", "symbol", "strike", "qty_btc", "exit_price", "exit_fee", "settle_S", "intrinsic", "hold_gain_usd"])
        w.writerows(new)


if __name__ == "__main__":
    main()
