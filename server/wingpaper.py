#!/usr/bin/env python3
"""wingpaper - PAPER ONLY, READ-ONLY (15-Nov-2026). "What if every live night sale also bought a far option?"

Follows the LIVE night seller's own trade log (logs/trades_night_nlive.csv) and never places or changes an order.
For every real SELL it notes, within a minute, the far option ("wing") of the same type and expiry whose strike is
WING_PCT (4 %) of the BTC price beyond the sold strike (CALL: lowest listed strike at or above; PUT: highest at or below;
none that far listed -> the farthest listed one, flagged; nothing beyond the sold strike -> no wing that night):
  best bid / ask, what buying the SAME quantity from the real asks would have averaged, whether that much was on offer.
When the night ends (NIGHT-END row) it notes what the wing could then be sold for (best bid; after expiry its settled value)
and writes one line per sale to logs/wingpaper.csv, then one email:
  wing cost in USD and as % of the premium, live night P&L, the same night WITH the wing, and the fixed worst loss.
Public market data only (no API key). State: state/wingpaper.json.
Usage: venv/bin/python wingpaper.py            (cron, every minute)
       venv/bin/python wingpaper.py --selftest (prices a pretend sale now; prints; writes nothing)
       venv/bin/python wingpaper.py --show     (prints the log so far)"""
import csv, json, os, socket, sys, time, datetime as dt
import urllib.request, urllib.parse
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
API = "https://api.india.delta.exchange"
TR = os.path.join(H, "logs", "trades_night_nlive.csv")
OUT = os.path.join(H, "logs", "wingpaper.csv")
ST = os.path.join(H, "state", "wingpaper.json")
WING_PCT = 0.04
C = 0.001
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
COLS = ["night", "sold_time", "side", "sold_symbol", "qty_btc", "sold_price", "spot", "wing_symbol", "extra_dist_pct", "fallback",
        "wing_bid", "wing_ask", "wing_avg_buy", "fully_on_offer", "wing_cost_usd", "cost_pct_of_premium", "wing_exit_price",
        "wing_net_usd", "fixed_worst_loss_usd", "live_night_pnl_usd", "night_wing_net_usd", "night_pnl_with_wing_usd"]


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "wingpaper/1"})
    return json.load(urllib.request.urlopen(req, timeout=10))["result"]


def fee(spot, price, qty):
    return min(0.0001 * spot * qty, 0.035 * price * qty) * 1.18


def parse(sym):
    p = sym.split("-")           # C-BTC-68200-151126
    return p[0], float(p[2]), p[3]


def spot_now():
    return float(get("/v2/tickers/BTCUSD")["mark_price"])


def strikes(typ, ddmmyy):
    """listed strikes of this type and expiry: {strike: symbol}"""
    date = "%s-%s-20%s" % (ddmmyy[0:2], ddmmyy[2:4], ddmmyy[4:6])
    out = {}
    for t in get("/v2/tickers", {"contract_types": "call_options,put_options", "underlying_asset_symbols": "BTC", "expiry_date": date}):
        p = str(t.get("symbol", "")).split("-")
        if len(p) == 4 and p[0] == typ and p[3] == ddmmyy:
            out[float(p[2])] = t["symbol"]
    return out


def book(sym):
    b = get("/v2/l2orderbook/" + sym, {"depth": 20})
    bids = sorted([(float(x["price"]), int(x["size"])) for x in (b.get("buy") or [])], key=lambda x: -x[0])
    asks = sorted([(float(x["price"]), int(x["size"])) for x in (b.get("sell") or [])], key=lambda x: x[0])
    return bids, asks


def pick_wing(typ, k, spot, listed):
    """(strike, fallback flag) or (None, 2)"""
    if typ == "C":
        far = [s for s in listed if s >= k + WING_PCT * spot]
        if far:
            return min(far), 0
        beyond = [s for s in listed if s > k]
        return (max(beyond), 1) if beyond else (None, 2)
    far = [s for s in listed if s <= k - WING_PCT * spot]
    if far:
        return max(far), 0
    beyond = [s for s in listed if s < k]
    return (min(beyond), 1) if beyond else (None, 2)


def quote_wing(sold_sym, qty_btc):
    """price the wing for one sale right now"""
    typ, k, exp = parse(sold_sym)
    spot = spot_now()
    listed = strikes(typ, exp)
    wk, fb = pick_wing(typ, k, spot, listed)
    d = dict(spot=spot, fb=fb, wing_sym="", wing_k=0, bid=0.0, ask=0.0, avg=0.0, full=False)
    if wk is None:
        return d
    bids, asks = book(listed[wk])
    n = int(round(qty_btc / C))
    left, got = n, 0.0
    for p, q in asks:
        take = min(left, q)
        got += take * p
        left -= take
        if left <= 0:
            break
    filled = n - max(left, 0)
    d.update(wing_sym=listed[wk], wing_k=wk, bid=bids[0][0] if bids else 0.0, ask=asks[0][0] if asks else 0.0,
             avg=(got / filled) if filled else 0.0, full=left <= 0)
    return d


def load():
    try:
        return json.load(open(ST))
    except Exception:
        return {"legs": {}, "done": []}


def save(S):
    os.makedirs(os.path.dirname(ST), exist_ok=True)
    json.dump(S, open(ST + ".tmp", "w"))
    os.replace(ST + ".tmp", ST)


def email(subject, body):
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(H, ".env"))
        sys.path.insert(0, H)
        import bot as B
        B.Notifier()._send_now("[DeltaBot PAPER] " + subject, body)
    except Exception as e:
        print("email failed:", repr(e))


def run():
    if not os.path.exists(TR):
        return
    first = not os.path.exists(ST)
    S = load()
    rows = list(csv.DictReader(open(TR)))
    if first:                                 # first run: nights already in the log are history, not to be priced or emailed
        S["done"] = sorted(set(r["night"] for r in rows if r.get("night")))
        save(S)
        print("first run: %d earlier nights marked as done" % len(S["done"]))
        return
    now = dt.datetime.now(IST)
    # A) new real sales -> note the wing now (only if we see the sale within 10 minutes; older ones are skipped)
    for r in rows:
        if r["event"] != "SELL" or not r.get("symbol"):
            continue
        key = "%s|%s|%s" % (r["time_ist"], r["symbol"], r["set"])
        if key in S["legs"] or r["night"] in S["done"]:
            continue
        t = dt.datetime.strptime(r["time_ist"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
        age = (now - t).total_seconds()
        leg = dict(night=r["night"], time=r["time_ist"], sym=r["symbol"], qty=float(r["qty_btc"]), px=float(r["price"]), late=age > 600)
        if age <= 600:
            try:
                leg.update(quote_wing(r["symbol"], leg["qty"]))
            except Exception as e:
                print(now.strftime("%F %T"), "wing quote failed", r["symbol"], repr(e))
                continue                      # try again next minute
        S["legs"][key] = leg
        save(S)
        print(now.strftime("%F %T"), "noted", key, {k: leg.get(k) for k in ("wing_sym", "ask", "avg", "full", "fb", "late")})
    # B) finished nights -> exit value, log, email
    ends = {r["night"]: r for r in rows if r["event"] == "NIGHT-END"}
    for night in sorted(set(l["night"] for l in S["legs"].values())):
        if night in S["done"] or night not in ends:
            continue
        legs = [l for l in S["legs"].values() if l["night"] == night]
        out, wing_net_total = [], 0.0
        for l in legs:
            typ, k, exp = parse(l["sym"])
            row = dict(night=night, sold_time=l["time"], side=typ, sold_symbol=l["sym"], qty_btc=l["qty"], sold_price=l["px"],
                       spot=round(l.get("spot", 0), 1), wing_symbol=l.get("wing_sym", ""), fallback=l.get("fb", "late" if l.get("late") else ""))
            if l.get("wing_sym") and l.get("avg"):
                wk = l["wing_k"]
                expiry = dt.datetime(2000 + int(exp[4:6]), int(exp[2:4]), int(exp[0:2]), 17, 30, tzinfo=IST)
                try:
                    sp = spot_now()
                    if now >= expiry:
                        xp = max(0.0, sp - wk) if typ == "C" else max(0.0, wk - sp)
                    else:
                        bids, _ = book(l["wing_sym"])
                        xp = bids[0][0] if bids else 0.0
                except Exception as e:
                    print(now.strftime("%F %T"), "exit quote failed", repr(e))
                    return                    # try again next minute
                cost = l["avg"] * l["qty"] + fee(l["spot"], l["avg"], l["qty"])
                back = xp * l["qty"] - (fee(sp, xp, l["qty"]) if xp > 0 and now < expiry else 0.0)
                net = back - cost
                wing_net_total += net
                row.update(extra_dist_pct=round(abs(wk - k) / l["spot"] * 100, 2), wing_bid=l["bid"], wing_ask=l["ask"],
                           wing_avg_buy=round(l["avg"], 2), fully_on_offer=l["full"], wing_cost_usd=round(cost, 4),
                           cost_pct_of_premium=round(100 * cost / (l["px"] * l["qty"]), 1) if l["px"] else "",
                           wing_exit_price=round(xp, 2), wing_net_usd=round(net, 4),
                           fixed_worst_loss_usd=round((abs(wk - k) - l["px"] + l["avg"]) * l["qty"], 2))
            out.append(row)
        live = float(ends[night]["pnl_usd"] or 0)
        for row in out:
            row.update(live_night_pnl_usd=round(live, 4), night_wing_net_usd=round(wing_net_total, 4),
                       night_pnl_with_wing_usd=round(live + wing_net_total, 4))
        new = not os.path.exists(OUT)
        with open(OUT, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            if new:
                w.writeheader()
            w.writerows(out)
        S["done"].append(night)
        S["legs"] = {k: v for k, v in S["legs"].items() if v["night"] != night}
        save(S)
        priced = [r for r in out if r.get("wing_avg_buy")]
        prem = sum(r["sold_price"] * r["qty_btc"] for r in priced)
        cost = sum(r["wing_cost_usd"] for r in priced)
        lines = ["%s x %.3f BTC sold @ %.1f | wing %s (%s%% further%s): ask %.1f, average for this size %.2f%s -> cost %.2f USD = %s%% of the premium; at the end worth %.2f" % (
            r["sold_symbol"], r["qty_btc"], r["sold_price"], r["wing_symbol"], r["extra_dist_pct"],
            ", nearest available" if r["fallback"] == 1 else "", r["wing_ask"], r["wing_avg_buy"],
            "" if r["fully_on_offer"] else " (NOT enough on offer)", r["wing_cost_usd"], r["cost_pct_of_premium"], r["wing_exit_price"])
            for r in priced] or ["no wing could be priced tonight (none listed beyond the sold strike, or the sale was seen too late)"]
        body = "\n".join(lines) + "\n\nLive night P&L %.2f USD | wing net %.2f USD | night WITH the wing %.2f USD" % (live, wing_net_total, live + wing_net_total)
        if priced:
            body += "\nWing cost %.1f%% of tonight's premium | fixed worst loss with the wing %.2f USD" % (
                100 * cost / prem if prem else 0, sum(r["fixed_worst_loss_usd"] for r in priced))
        body += "\n(paper only - nothing was bought; log: logs/wingpaper.csv)"
        email("WING PAPER night %s: with 4%% far option %.2f USD (live %.2f)" % (night, live + wing_net_total, live), body)
        print(now.strftime("%F %T"), "night", night, "logged:", body.replace("\n", " | "))


def selftest():
    sp = spot_now()
    exp = dt.datetime.now(dt.timezone.utc)
    e = exp.replace(hour=12, minute=0, second=0, microsecond=0)
    if e <= exp:
        e += dt.timedelta(days=1)
    dd = e.strftime("%d%m%y")
    for typ in ("C", "P"):
        ks = strikes(typ, dd)
        tgt = sp * (1.033 if typ == "C" else 0.967)
        cand = [s for s in ks if (s >= tgt if typ == "C" else s <= tgt)]
        if not cand:
            print(typ, "no strike 3.3% out"); continue
        k = min(cand) if typ == "C" else max(cand)
        bids, asks = book(ks[k])
        q = quote_wing(ks[k], 0.36)
        print("%s spot %.0f | pretend sale %s bid %s | listed strikes %d (%.0f..%.0f) | wing %s fallback %s bid %.1f ask %.1f avg for 0.36 BTC %.2f full %s | cost %s%% of the bid" % (
            typ, sp, ks[k], bids[0][0] if bids else None, len(ks), min(ks), max(ks), q["wing_sym"], q["fb"], q["bid"], q["ask"], q["avg"], q["full"],
            round(100 * q["avg"] / bids[0][0], 1) if bids and bids[0][0] else "n/a"))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--show" in sys.argv:
        print(open(OUT).read() if os.path.exists(OUT) else "no nights logged yet")
    else:
        run()
