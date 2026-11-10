#!/usr/bin/env python3
"""callmargin - READ-ONLY logger of the REAL margin Delta blocks on the Ladderv9 account (10-Nov-2026).
Why: Delta has not confirmed how much initial margin a short option blocks (ticket #484314). Sudip wants it measured every
day without his PC. This script only sends GET requests (positions, wallet, BTCUSD price). It NEVER places or changes orders,
never changes leverage, never touches any bot or service.

  venv/bin/python callmargin.py            one reading now -> logs/callmargin.csv (+ raw JSON in logs/callmargin_raw.jsonl)
  venv/bin/python callmargin.py --show     same but only prints, writes nothing
  venv/bin/python callmargin.py --summary  emails today's 17:30-17:50 IST readings (cron 17:50)
Account: env CM_ACCT (default ladder9). Server time is IST."""
import os, sys, csv, json, datetime as dt

H = os.path.expanduser("~/deltabot")
sys.path.insert(0, H)
os.chdir(H)
from liveorders import Live, Pub  # same read-only client the capital manager uses

ACCT = os.environ.get("CM_ACCT", "ladder9")
CPB = 1000.0  # contracts per BTC (1 contract = 0.001 BTC), same for BTCUSD and BTC options
CSV = os.path.join(H, "logs", "callmargin.csv")
RAW = os.path.join(H, "logs", "callmargin_raw.jsonl")
COLS = ["time_ist", "index", "wallet_balance", "blocked_margin", "available", "symbol", "size_contracts", "btc",
        "entry_price", "mark_price", "margin", "notional_at_index", "margin_over_notional", "upnl"]


def f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def sample():
    lv, pub = Live(ACCT), Pub()
    pos = lv._p("GET", "/v2/positions/margined")["result"] or []
    bal = lv._p("GET", "/v2/wallet/balances")["result"] or []
    tk = pub._http("GET", "/v2/tickers/BTCUSD")["result"]
    idx = f(tk.get("spot_price")) or f(tk.get("mark_price"))
    rows_b = [b for b in bal if f(b.get("balance")) > 0]
    b0 = rows_b[0] if rows_b else {}
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wallet, blocked, avail = f(b0.get("balance")), f(b0.get("blocked_margin")), f(b0.get("available_balance"))
    out = []
    for r in pos:
        sz = f(r.get("size"))
        if not sz:
            continue
        btc = abs(sz) / CPB
        notional = btc * idx
        margin = f(r.get("margin"))
        out.append({"time_ist": now, "index": round(idx, 1), "wallet_balance": round(wallet, 2),
                    "blocked_margin": round(blocked, 2), "available": round(avail, 2),
                    "symbol": r.get("product_symbol"), "size_contracts": sz, "btc": round(btc, 4),
                    "entry_price": r.get("entry_price"), "mark_price": r.get("mark_price"),
                    "margin": round(margin, 2), "notional_at_index": round(notional, 2),
                    "margin_over_notional": round(margin / notional, 4) if notional else "",
                    "upnl": r.get("unrealized_pnl")})
    if not out:
        out.append({"time_ist": now, "index": round(idx, 1), "wallet_balance": round(wallet, 2),
                    "blocked_margin": round(blocked, 2), "available": round(avail, 2), "symbol": "", "size_contracts": 0,
                    "btc": 0, "entry_price": "", "mark_price": "", "margin": 0, "notional_at_index": 0,
                    "margin_over_notional": "", "upnl": ""})
    return out, {"time_ist": now, "positions": pos, "balance": b0}


def show(rows):
    for r in rows:
        print(" | ".join("%s=%s" % (k, r[k]) for k in COLS))


def write(rows, raw):
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    new = not os.path.exists(CSV)
    with open(CSV, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerows(rows)
    with open(RAW, "a") as fh:
        fh.write(json.dumps(raw, default=str) + "\n")


def summary():
    day = dt.datetime.now().strftime("%Y-%m-%d")
    rows = []
    if os.path.exists(CSV):
        for r in csv.DictReader(open(CSV)):
            if r["time_ist"].startswith(day) and "17:30:00" <= r["time_ist"][11:] <= "17:50:59":
                rows.append(r)
    opt = [r for r in rows if r["symbol"][:2] in ("C-", "P-")]
    lines = ["Ladderv9 REAL margin blocked on short options, %s 17:30-17:50 IST (read-only, from Delta's API)" % day]
    if not opt:
        lines.append("No option position was open in this window.")
        allr = [r for r in rows if r["symbol"] == "" or True]
        if allr:
            last = allr[-1]
            lines.append("Account at %s: wallet %s, blocked %s, available %s" % (
                last["time_ist"][11:16], last["wallet_balance"], last["blocked_margin"], last["available"]))
    else:
        first, last = opt[0], opt[-1]
        ratios = [float(r["margin_over_notional"]) for r in opt if r["margin_over_notional"]]
        lines.append("Symbol %s, %s BTC short" % (last["symbol"], last["btc"]))
        lines.append("First reading %s: margin %s on notional %s = %s of notional (about %sx)" % (
            first["time_ist"][11:16], first["margin"], first["notional_at_index"], first["margin_over_notional"],
            round(1 / float(first["margin_over_notional"]), 2) if first["margin_over_notional"] and float(first["margin_over_notional"]) else "n/a"))
        lines.append("Last reading %s: margin %s on notional %s = %s of notional; index %s" % (
            last["time_ist"][11:16], last["margin"], last["notional_at_index"], last["margin_over_notional"], last["index"]))
        if ratios:
            lines.append("Ratio range in window: %.4f to %.4f (expect about 0.5 at 2x, 1.0 at 1x)" % (min(ratios), max(ratios)))
        lines.append("Account: wallet %s, blocked %s, available %s" % (last["wallet_balance"], last["blocked_margin"], last["available"]))
    body = "\n".join(lines)
    print(body)
    try:
        import bot
        bot.Notifier()._send_now("[DeltaBot LIVE] Ladderv9 call margin report %s" % day, body)
    except Exception as e:
        print("email failed:", e)


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summary()
    else:
        rows, raw = sample()
        if "--show" in sys.argv:
            show(rows)
        else:
            write(rows, raw)
