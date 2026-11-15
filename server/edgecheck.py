#!/usr/bin/env python3
"""edgecheck - READ-ONLY (15-Nov-2026). "Is the night sell still earning what the 6.6-year test says it should?"

Reads the LIVE night seller's own trade log (logs/trades_night_nlive.csv) and public Delta BTC candles. Never places
or changes an order, uses no API key. Once a month (cron) it emails a short report and adds a line to logs/edgecheck.csv:

 1. STRIKE TOUCHED   - share of traded nights on which BTC reached the sold strike while the sale was open.
                       Test value 5.6 % (1 night in 18). Red line: 12 %.
 2. PAY-OUT          - what the sold options were worth at expiry (had they simply been held) as a share of the premium
                       collected. Test value about 35 %. Red line: 70 %. At 100 % the premium no longer pays for the moves.
 3. NIGHTS FOR ONE WORST NIGHT - the test's worst night (per 0.01 BTC sold, scaled to today's BTC price) divided by the
                       real average profit per traded night (per 0.01 BTC sold). Test value about 84. Red line: 170.
 4. STOP RULE        - real running P&L: days since its last peak and how far below the peak it is.
                       STOP AND REVIEW when below the peak for more than 548 days (18 months), or down by more than
                       two worst nights at the current base (Sudip, 15-Nov-2026; to be calibrated later).
Measures 1-3 use the last 100 traded nights (all nights while fewer); under 60 nights they are marked "indicative only".
Usage: venv/bin/python edgecheck.py           (cron, monthly: emails + logs)
       venv/bin/python edgecheck.py --show    (print only)"""
import csv, json, os, socket, sys, time, datetime as dt
import urllib.request, urllib.parse
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
API = "https://api.india.delta.exchange"
TR = os.path.join(H, "logs", "trades_night_nlive.csv")
OUT = os.path.join(H, "logs", "edgecheck.csv")
CACHE = os.path.join(H, "state", "edgecheck_nights.json")
CFG = os.path.join(H, "state", "night_live_cfg.json")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
FX = 85.0
WINDOW, MIN_NIGHTS = 100, 60
BM = dict(touch=0.056, payout=0.35, net_per_001_sold_rs=38.0, worst_per_001_sold_rs=3194.0, worst_per_001_base_rs=9583.0, price=82000.0)
RED = dict(touch=0.12, payout=0.70, nights_for_worst=170.0, days_under=548, dd_worst_nights=2.0)
COLS = ["run_time", "traded_nights", "window_nights", "touch_pct", "payout_pct", "net_rs_per_001_sold", "nights_for_one_worst",
        "total_pnl_usd", "peak_usd", "drawdown_usd", "days_since_peak", "base", "btc_price", "flags"]


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "edgecheck/1"})
    return json.load(urllib.request.urlopen(req, timeout=15))["result"]


def candles(start, end):
    r = get("/v2/history/candles", {"resolution": "5m", "symbol": "BTCUSD", "start": int(start), "end": int(end)})
    return sorted(r, key=lambda x: x["time"])


def ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST).timestamp()


def nights():
    """one dict per finished night from the live trade log"""
    N = {}
    for r in csv.DictReader(open(TR)):
        n = N.setdefault(r["night"], dict(night=r["night"], sells=[], last_exit=0, pnl=None, end=None))
        if r["event"] == "SELL" and r.get("symbol"):
            n["sells"].append(dict(t=ts(r["time_ist"]), sym=r["symbol"], qty=float(r["qty_btc"]), px=float(r["price"])))
        elif r["event"].startswith("EXIT") or r["event"].startswith("SETTLE"):
            n["last_exit"] = max(n["last_exit"], ts(r["time_ist"]))
        elif r["event"] == "NIGHT-END":
            n["pnl"], n["end"] = float(r["pnl_usd"] or 0), ts(r["time_ist"])
    return [n for n in N.values() if n["night"] and n["pnl"] is not None]


def enrich(n, cache):
    """strike touched while open? value at expiry? (cached per night)"""
    if n["night"] in cache:
        return cache[n["night"]]
    d = dict(touched=False, intrinsic_usd=0.0, premium_usd=0.0, sold_btc=0.0)
    if n["sells"]:
        t0 = min(s["t"] for s in n["sells"])
        day = dt.datetime.strptime(n["night"], "%Y-%m-%d").replace(tzinfo=IST)
        expiry = (day + dt.timedelta(days=1)).replace(hour=17, minute=30).timestamp()
        t_close = min(n["last_exit"] or n["end"] or expiry, expiry)
        cs = candles(t0 - 300, expiry + 300)
        if not cs:
            return None
        settle = [c for c in cs if c["time"] <= expiry]
        s_exp = float(settle[-1]["close"]) if settle else float(cs[-1]["close"])
        for s in n["sells"]:
            typ, k = s["sym"].split("-")[0], float(s["sym"].split("-")[2])
            op = [c for c in cs if t0 - 300 <= c["time"] <= t_close]
            if op and ((typ == "C" and max(float(c["high"]) for c in op) >= k) or (typ == "P" and min(float(c["low"]) for c in op) <= k)):
                d["touched"] = True
            d["intrinsic_usd"] += (max(0.0, s_exp - k) if typ == "C" else max(0.0, k - s_exp)) * s["qty"]
            d["premium_usd"] += s["px"] * s["qty"]
            d["sold_btc"] += s["qty"]
    cache[n["night"]] = d
    return d


def email(subject, body):
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(H, ".env"))
        sys.path.insert(0, H)
        import bot as B
        B.Notifier()._send_now("[DeltaBot] " + subject, body)
    except Exception as e:
        print("email failed:", repr(e))


def report():
    try:
        cache = json.load(open(CACHE))
    except Exception:
        cache = {}
    N = sorted(nights(), key=lambda n: n["night"])
    rows = []
    for n in N:
        if not n["sells"]:
            continue
        e = enrich(n, cache)
        if e is None:
            continue
        rows.append(dict(n, **e))
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, "w"))
    price = float(get("/v2/tickers/BTCUSD")["mark_price"])
    try:
        base = float(json.load(open(CFG)).get("base", 0))
    except Exception:
        base = 0.0
    W = rows[-WINDOW:]
    k = price / BM["price"]
    out = dict(run_time=dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"), traded_nights=len(rows), window_nights=len(W),
               base=base, btc_price=round(price))
    flags, L = [], []
    if W:
        touch = sum(1 for r in W if r["touched"]) / len(W)
        prem = sum(r["premium_usd"] for r in W)
        payout = sum(r["intrinsic_usd"] for r in W) / prem if prem else 0.0
        sold = sum(r["sold_btc"] for r in W)
        net_per_night = (sum(r["pnl"] for r in W) / len(W)) / (sold / len(W)) * 0.01 * FX if sold else 0.0
        worst = BM["worst_per_001_sold_rs"] * k
        nfw = worst / net_per_night if net_per_night > 0 else float("inf")
        out.update(touch_pct=round(100 * touch, 1), payout_pct=round(100 * payout, 1), net_rs_per_001_sold=round(net_per_night, 1),
                   nights_for_one_worst=round(nfw, 0) if nfw != float("inf") else "inf")
        few = len(W) < MIN_NIGHTS
        L.append("Nights used: last %d traded nights%s" % (len(W), " - FEWER THAN %d, figures are indicative only" % MIN_NIGHTS if few else ""))
        L.append("1. Strike touched: %.1f %% of nights (test 5.6 %%, red line 12 %%)" % (100 * touch))
        L.append("2. Pay-out: options were worth %.0f %% of the premium at expiry (test about 35 %%, red line 70 %%)" % (100 * payout))
        L.append("3. Profit per traded night: Rs %.0f per 0.01 BTC sold (test Rs %.0f at today's price); one worst night = %s such nights (test about 84, red line 170)" % (
            net_per_night, BM["net_per_001_sold_rs"] * k, ("%.0f" % nfw) if nfw != float("inf") else "no profit yet -"))
        if not few:
            if touch > RED["touch"]: flags.append("strike touched too often")
            if payout > RED["payout"]: flags.append("pay-out above the red line")
            if nfw > RED["nights_for_worst"]: flags.append("profit per night too thin for the worst night")
    # stop rule on the real running P&L
    cum, peak, peak_t, tot = 0.0, 0.0, None, 0.0
    for n in N:
        cum += n["pnl"]
        if cum >= peak:
            peak, peak_t = cum, n["night"]
    tot = cum
    ddn = peak - tot
    first = N[0]["night"] if N else None
    ref = peak_t or first
    days = (dt.datetime.now(IST).date() - dt.datetime.strptime(ref, "%Y-%m-%d").date()).days if ref else 0
    worst_now_usd = BM["worst_per_001_base_rs"] * k * (base / 0.01) / FX if base else 0.0
    out.update(total_pnl_usd=round(tot, 2), peak_usd=round(peak, 2), drawdown_usd=round(ddn, 2), days_since_peak=days)
    L.append("4. Running P&L %.2f USD (Rs %.0f) | peak %.2f on %s | now %.2f below the peak, %d days since the peak" % (
        tot, tot * FX, peak, peak_t or "-", ddn, days if ddn > 0 else 0))
    L.append("   Stop rule: review if below the peak for more than 548 days, or down by more than %.0f USD (two worst nights at base %.2f)" % (
        RED["dd_worst_nights"] * worst_now_usd, base))
    if ddn > 0 and days > RED["days_under"]: flags.append("STOP AND REVIEW: below the peak for more than 18 months")
    if worst_now_usd and ddn > RED["dd_worst_nights"] * worst_now_usd: flags.append("STOP AND REVIEW: down by more than two worst nights")
    out["flags"] = "; ".join(flags)
    verdict = ("RED: " + "; ".join(flags)) if flags else "all inside the lines"
    return out, "Night sell edge check - %s\n\n%s\n\nBTC %.0f, base %.2f. Read-only report; nothing was changed." % (verdict, "\n".join(L), price, base), verdict


if __name__ == "__main__":
    out, body, verdict = report()
    print(body)
    if "--show" not in sys.argv:
        new = not os.path.exists(OUT)
        with open(OUT, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            if new:
                w.writeheader()
            w.writerow({c: out.get(c, "") for c in COLS})
        email("EDGE CHECK (night sell): %s" % verdict, body)
