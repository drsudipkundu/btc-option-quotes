#!/usr/bin/env python3
"""fillquality - READ-ONLY (12-Nov-2026). How good were the REAL night-sell fills compared with the recorded order book?

For every SELL row in logs/trades_night_nlive.csv it finds the recorded books (optbook/YYYYMMDD_23.jsonl[.gz], one snapshot about
every 30 s) of the same option around the sale time and writes one line to logs/fillquality.csv:
  best bid / best ask just BEFORE the sale (latest snapshot at or before the sale time, at most ~30-60 s old)
  spread, contracts resting at the best bid, contracts within 5 % and 10 % of the best bid
  fill price as % of that best bid (slippage; below 100 % = sold under the bid; above = sold above it, resting order filled)
  what a straight sweep of the same size into the bids would have averaged (% of best bid)
  capacity: the largest size (contracts) a sweep could sell at 95 % of the best bid or better
Never places or changes an order. Safe to run any time; skips sales already logged.
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
    if show or not rows:
        return
    new = not os.path.exists(OUTF)
    with open(OUTF, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
