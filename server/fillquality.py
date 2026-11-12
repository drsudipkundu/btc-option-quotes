#!/usr/bin/env python3
"""fillquality - READ-ONLY (12-Nov-2026). How good were the REAL night-sell fills compared with the recorded order book?

For every SELL row in logs/trades_night_nlive.csv it finds the recorded books (optbook/YYYYMMDD_23.jsonl[.gz], one snapshot about
every 30 s) of the same option around the sale time and writes one line to logs/fillquality.csv:
  best bid / best ask just BEFORE the sale (latest snapshot at or before the sale time, at most ~30-60 s old)
  spread, contracts resting at the best bid, contracts within 5 % and 10 % of the best bid
  fill price as % of that best bid (slippage; below 100 % = sold under the bid; above = sold above it, resting order filled)
  what a straight sweep of the same size into the bids would have averaged (% of best bid)
  capacity: the largest size (contracts) a sweep could sell at 95 % of the best bid or better
Also (12-Nov-2026, second log logs/fillquality_buys.csv): every non-sale trade row with a symbol and size - the resting 90 % buy-back
(EXIT-90PCT), crash-guard insurance buys and any other buy - is matched to the book of that hour: best bid/ask just before, ask depth,
fill price as % of the best ask (below 100 % = bought cheaper than paying the ask), straight-buy average, capacity at <= 105 % of the ask.
Never places or changes an order. Safe to run any time; skips rows already logged.
Usage: venv/bin/python fillquality.py          (cron once a day, 06:10 IST)
       venv/bin/python fillquality.py --show   (print only, write nothing)"""
import csv, glob, gzip, json, os, sys, datetime as dt

H = os.path.expanduser("~/deltabot")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TR = os.path.join(H, "logs", "trades_night_nlive.csv")
OUTF = os.path.join(H, "logs", "fillquality.csv")
BOOKS = os.path.join(H, "optbook")
COLS = ["time_ist", "symbol", "set", "qty_contracts", "fill_price", "book_age_s", "best_bid", "best_ask", "spread_pct",
        "bid_contracts", "bid_within5pct", "bid_within10pct", "fill_vs_bid_pct", "sweep_vs_bid_pct", "capacity_95pct_contracts"]


def sweep(bids, n):
    left, got = n, 0.0
    for p, q in bids:
        take = min(left, q)
        got += take * p
        left -= take
        if left <= 0:
            break
    filled = n - max(left, 0)
    return (got / filled) if filled else 0.0, filled


def load(day):
    """snapshots of one night: {symbol: [(unix, bids, asks)]} from the 23:xx hour file of that date"""
    out = {}
    for f in glob.glob(os.path.join(BOOKS, day.strftime("%Y%m%d") + "_23.jsonl*")):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt") as fh:
            for ln in fh:
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                out.setdefault(r["s"], []).append((r["t"], r["bids"], r["asks"]))
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out


OUTB = os.path.join(H, "logs", "fillquality_buys.csv")
COLB = ["time_ist", "event", "symbol", "qty_contracts", "fill_price", "book_age_s", "best_bid", "best_ask", "spread_pct",
        "ask_contracts", "ask_within5pct", "fill_vs_ask_pct", "buy_sweep_vs_ask_pct", "capacity_105pct_contracts"]


def load_hour(t):
    """snapshots {symbol: [(unix, bids, asks)]} from the hourly file(s) of the hour of t and the hour before it"""
    out = {}
    for h in (t - dt.timedelta(hours=1), t):
        for f in glob.glob(os.path.join(BOOKS, h.strftime("%Y%m%d_%H") + ".jsonl*")):
            op = gzip.open if f.endswith(".gz") else open
            try:
                with op(f, "rt") as fh:
                    for ln in fh:
                        try:
                            r = json.loads(ln)
                        except Exception:
                            continue
                        out.setdefault(r["s"], []).append((r["t"], r["bids"], r["asks"]))
            except Exception:
                continue
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out


def buys(show):
    done = set()
    if os.path.exists(OUTB):
        with open(OUTB) as fh:
            for r in csv.DictReader(fh):
                done.add((r["time_ist"], r["event"], r["symbol"]))
    rows, cache = [], {}
    with open(TR) as fh:
        for r in csv.DictReader(fh):
            if r["event"] in ("SELL", "NIGHT-END") or not r.get("symbol") or not float(r.get("qty_btc") or 0):
                continue
            key = (r["time_ist"], r["event"], r["symbol"])
            if key in done:
                continue
            t = dt.datetime.strptime(r["time_ist"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
            hk = t.strftime("%Y%m%d%H")
            if hk not in cache:
                cache[hk] = load_hour(t)
            snaps = [x for x in cache[hk].get(r["symbol"], []) if x[0] <= t.timestamp() + 1]
            if not snaps:
                continue
            ts, bids, asks = snaps[-1]
            if t.timestamp() - ts > 600 or not asks:
                continue
            n = int(round(float(r["qty_btc"]) * 1000))
            price = float(r["price"])
            ask = asks[0][0]
            bid = bids[0][0] if bids else 0
            a5 = sum(q for p, q in asks if p <= ask * 1.05)
            left, got = n, 0.0
            for p, q in asks:
                take = min(left, q)
                got += take * p
                left -= take
                if left <= 0:
                    break
            sw = (got / n / ask * 100) if left <= 0 else None
            cap = 0
            for m in range(5, int(sum(q for p, q in asks)) + 1, 5):
                l2, g2 = m, 0.0
                for p, q in asks:
                    tk = min(l2, q)
                    g2 += tk * p
                    l2 -= tk
                    if l2 <= 0:
                        break
                if l2 > 0 or g2 / m > 1.05 * ask:
                    break
                cap = m
            rows.append(dict(time_ist=r["time_ist"], event=r["event"], symbol=r["symbol"], qty_contracts=n, fill_price=price,
                             book_age_s=round(t.timestamp() - ts), best_bid=bid, best_ask=ask,
                             spread_pct=round((ask - bid) / ask * 100, 1) if bid and ask else "", ask_contracts=asks[0][1],
                             ask_within5pct=a5, fill_vs_ask_pct=round(price / ask * 100, 1),
                             buy_sweep_vs_ask_pct=round(sw, 1) if sw else "not fully fillable", capacity_105pct_contracts=cap))
    for r in rows:
        print("%s %s %s %d lots @ %.2f | bid %s ask %.2f | ask side at best %d lots, within 5 %% %d | fill = %s %% of ask | straight buy = %s %% | capacity %d lots" % (
            r["time_ist"][5:16], r["event"], r["symbol"][6:], r["qty_contracts"], r["fill_price"], r["best_bid"], r["best_ask"],
            r["ask_contracts"], r["ask_within5pct"], r["fill_vs_ask_pct"], r["buy_sweep_vs_ask_pct"], r["capacity_105pct_contracts"]))
    if not rows:
        print("no new buys to log")
    if show or not rows:
        return
    new = not os.path.exists(OUTB)
    with open(OUTB, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLB)
        if new:
            w.writeheader()
        w.writerows(rows)


def main():
    show = "--show" in sys.argv
    done = set()
    if os.path.exists(OUTF):
        with open(OUTF) as fh:
            for r in csv.DictReader(fh):
                done.add((r["time_ist"], r["symbol"], r["set"]))
    rows, cache = [], {}
    with open(TR) as fh:
        for r in csv.DictReader(fh):
            if r["event"] != "SELL":
                continue
            key = (r["time_ist"], r["symbol"], r["set"])
            if key in done:
                continue
            t = dt.datetime.strptime(r["time_ist"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
            d = t.date()
            if d not in cache:
                cache[d] = load(t)
            snaps = [s for s in cache[d].get(r["symbol"], []) if s[0] <= t.timestamp() + 1]
            if not snaps:
                continue
            ts, bids, asks = snaps[-1]
            if t.timestamp() - ts > 120 or not bids:
                continue
            n = int(round(float(r["qty_btc"]) * 1000))
            price = float(r["price"])
            best = bids[0][0]
            ask = asks[0][0] if asks else 0
            w5 = sum(q for p, q in bids if p >= best * 0.95)
            w10 = sum(q for p, q in bids if p >= best * 0.90)
            sw, filled = sweep(bids, n)
            cap = 0
            for m in range(5, int(sum(q for p, q in bids)) + 1, 5):
                a, f = sweep(bids, m)
                if f < m or a < 0.95 * best:
                    break
                cap = m
            rows.append(dict(time_ist=r["time_ist"], symbol=r["symbol"], set=r["set"], qty_contracts=n, fill_price=price,
                             book_age_s=round(t.timestamp() - ts), best_bid=best, best_ask=ask,
                             spread_pct=round((ask - best) / best * 100, 1) if ask and best else "", bid_contracts=bids[0][1],
                             bid_within5pct=w5, bid_within10pct=w10, fill_vs_bid_pct=round(price / best * 100, 1),
                             sweep_vs_bid_pct=round(sw / best * 100, 1) if filled == n else "not fully fillable",
                             capacity_95pct_contracts=cap))
    for r in rows:
        print("%s %s %d lots @ %.1f | bid %.1f ask %.1f spread %s %% | at best bid %d lots, within 5 %% %d, within 10 %% %d | fill = %s %% of bid | sweep = %s %% | capacity %d lots" % (
            r["time_ist"][5:16], r["symbol"][6:], r["qty_contracts"], r["fill_price"], r["best_bid"], r["best_ask"], r["spread_pct"],
            r["bid_contracts"], r["bid_within5pct"], r["bid_within10pct"], r["fill_vs_bid_pct"], r["sweep_vs_bid_pct"],
            r["capacity_95pct_contracts"]))
    if not rows:
        print("no new sales to log")
    if not (show or not rows):
        new = not os.path.exists(OUTF)
        with open(OUTF, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            if new:
                w.writeheader()
            w.writerows(rows)
    buys(show)


if __name__ == "__main__":
    main()
