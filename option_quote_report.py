r"""
option_quote_report.py -- what the covered call and the protective puts REALLY cost, from recorded quotes.

Reads every snapshot in this repository copy (data/**/*.csv.gz and parquet/*.parquet) and writes, for a
date range, four CSVs plus a short markdown summary:

  1. sells.csv     each day at 17:35 IST: the daily-expiry CALL nearest delta 0.03 (expiring tomorrow
                   17:30 IST) -> strike, % above spot, bid, ask, mark, spread % of mark
                   = "what we could actually sell it for" (we sell at the BID)
  2. roundtrip.csv the same contract next day 17:20-17:29 IST -> ask each minute = "what we pay to buy
                   it back" (we buy at the ASK), and the round trip per lot (0.001 BTC) after fees
  3. spreads.csv   median spread % of mark by |delta| bucket x hour of day (IST) x call/put x daily/weekly/monthly
  4. puts.csv      each day at 17:35 IST: monthly puts nearest delta -0.05 and -0.10 -> ask = cost of protection

Delta Exchange option fee per side = min(0.01 % of notional, 3.5 % of premium) + 18 % GST,
notional = spot x 0.001 BTC per lot. Quotes with an empty side, or sitting on Delta's price-band
limit (bid_at_floor / ask_at_cap), are never used as a price.

    python option_quote_report.py                               # everything recorded
    python option_quote_report.py --start 2026-10-01 --end 2026-10-31 --out reports
"""
import argparse
import glob
import os
import sys
from datetime import time

import pandas as pd

LOT_BTC = 0.001
FEE_NOTIONAL, FEE_PREMIUM_CAP, GST = 0.0001, 0.035, 0.18
SELL_IST = time(17, 35)
SELL_TOLERANCE_MIN = 5                     # use the snapshot nearest 17:35 within +/- this
BUYBACK_IST = (time(17, 20), time(17, 29))
TARGET_DELTA = 0.03
PUT_DELTAS = (-0.05, -0.10)
BUCKETS = [(0.01, 0.05), (0.05, 0.10), (0.10, 0.30)]
HERE = os.path.dirname(os.path.abspath(__file__))


def load(root, start, end):
    frames = [pd.read_parquet(p) for p in sorted(glob.glob(os.path.join(root, "parquet", "*.parquet")))]
    frames += [pd.read_csv(p) for p in sorted(glob.glob(os.path.join(root, "data", "*", "*", "*", "quotes_*.csv.gz")))]
    if not frames:
        sys.exit(f"no snapshots found under {root}")
    df = pd.concat(frames, ignore_index=True)
    for c in ("ts_utc", "expiry_utc"):
        df[c] = pd.to_datetime(df[c], utc=True, format="ISO8601")
    df["ts_ist"] = df["ts_utc"].dt.tz_convert("Asia/Kolkata")
    df["day_ist"] = df["ts_ist"].dt.date
    if start:
        df = df[df["day_ist"] >= pd.Timestamp(start).date()]
    if end:
        df = df[df["day_ist"] <= pd.Timestamp(end).date()]
    # one row per (minute, symbol): the evening and half-hourly runs can both land on 17:30 IST
    df = df.sort_values("fetch_utc").drop_duplicates(["ts_utc", "symbol"], keep="first")
    df["usable_bid"] = df["best_bid"].where(df["best_bid"].notna() & ~df["bid_at_floor"].astype(bool))
    df["usable_ask"] = df["best_ask"].where(df["best_ask"].notna() & ~df["ask_at_cap"].astype(bool))
    tags = df["expiry_tags"].fillna("")
    df["series"] = "daily"
    df.loc[tags.str.contains("weekly"), "series"] = "weekly"
    df.loc[tags.str.contains("monthly"), "series"] = "monthly"
    return df


def fee(price, spot):
    """One side, one lot, USD."""
    return min(FEE_NOTIONAL * spot * LOT_BTC, FEE_PREMIUM_CAP * price * LOT_BTC) * (1 + GST)


def snapshot_near(df, day, at):
    """Rows of the snapshot nearest IST `at` on `day`, within SELL_TOLERANCE_MIN, else empty."""
    target = pd.Timestamp.combine(day, at).tz_localize("Asia/Kolkata")
    times = df.loc[df["day_ist"] == day, "ts_ist"].drop_duplicates()
    if times.empty:
        return df.iloc[0:0], None
    best = times.iloc[(times - target).abs().argmin()]
    if abs((best - target).total_seconds()) > SELL_TOLERANCE_MIN * 60:
        return df.iloc[0:0], None
    return df[df["ts_ist"] == best], best


def sells_and_roundtrips(df):
    sells, trips = [], []
    for day in sorted(df["day_ist"].unique()):
        snap, at = snapshot_near(df, day, SELL_IST)
        if at is None:
            sells.append({"day": day, "note": "no snapshot near 17:35 IST"})
            continue
        # tomorrow-expiring calls = the nearest expiry after this snapshot
        calls = snap[(snap["type"] == "C") & snap["expiry_utc"].notna() & (snap["expiry_utc"] > snap["ts_utc"])]
        if calls.empty:
            sells.append({"day": day, "note": "no calls in snapshot"})
            continue
        calls = calls[calls["expiry_utc"] == calls["expiry_utc"].min()].dropna(subset=["delta"])
        r = calls.loc[(calls["delta"] - TARGET_DELTA).abs().idxmin()]
        s = {"day": day, "snapshot_ist": at.strftime("%H:%M"), "symbol": r["symbol"], "strike": r["strike"],
             "spot": r["spot"], "pct_above_spot": round((r["strike"] / r["spot"] - 1) * 100, 2),
             "delta": r["delta"], "bid": r["usable_bid"], "ask": r["usable_ask"], "mark": r["mark"],
             "spread_pct_mark": r["spread_pct_mark"], "bid_size": r["bid_size"]}
        sells.append(s)

        # next day's buy-back window, same symbol
        nxt = df[(df["symbol"] == r["symbol"]) & (df["day_ist"] == day + pd.Timedelta(days=1))]
        w = nxt[(nxt["ts_ist"].dt.time >= BUYBACK_IST[0]) & (nxt["ts_ist"].dt.time <= BUYBACK_IST[1])]
        t = {"sell_day": day, "symbol": r["symbol"], "sell_bid": s["bid"], "minutes_recorded": len(w),
             "minutes_with_ask": int(w["usable_ask"].notna().sum())}
        if w["usable_ask"].notna().any() and pd.notna(s["bid"]):
            last = w.dropna(subset=["usable_ask"]).iloc[-1]
            t.update({"ask_min": w["usable_ask"].min(), "ask_median": w["usable_ask"].median(),
                      "ask_last": last["usable_ask"], "ask_last_ist": last["ts_ist"].strftime("%H:%M"),
                      "bid_median": w["usable_bid"].median()})
            spot = last["spot"]
            for k in ("ask_median", "ask_last"):
                gross = (s["bid"] - t[k]) * LOT_BTC
                fees = fee(s["bid"], s["spot"]) + fee(t[k], spot)
                t[f"net_per_lot_usd_{k}"] = round(gross - fees, 4)
            t["fees_per_lot_usd"] = round(fee(s["bid"], s["spot"]) + fee(t["ask_median"], spot), 4)
            t["spread_cost_per_lot_usd"] = round(((s["ask"] - s["bid"]) / 2 if pd.notna(s["ask"]) else 0) * LOT_BTC
                                                 + (t["ask_median"] - w["usable_bid"].median()) / 2 * LOT_BTC, 4) \
                if pd.notna(w["usable_bid"].median()) else None
        else:
            t["note"] = "no usable ask recorded 17:20-17:29 IST next day" if len(w) else "next-day window not recorded"
        trips.append(t)
    return pd.DataFrame(sells), pd.DataFrame(trips)


def spreads(df):
    o = df[df["type"].isin(["C", "P"]) & df["usable_bid"].notna() & df["usable_ask"].notna() & df["delta"].notna()].copy()
    o["abs_delta"] = o["delta"].abs()
    o["bucket"] = None
    for lo, hi in BUCKETS:
        o.loc[(o["abs_delta"] >= lo) & (o["abs_delta"] < hi), "bucket"] = f"{lo:.2f}-{hi:.2f}"
    o = o.dropna(subset=["bucket"])
    o["hour_ist"] = o["ts_ist"].dt.hour
    g = o.groupby(["series", "type", "bucket", "hour_ist"])["spread_pct_mark"]
    return g.agg(median="median", p75=lambda x: x.quantile(0.75), n="size").round(3).reset_index()


def puts(df):
    out = []
    for day in sorted(df["day_ist"].unique()):
        snap, at = snapshot_near(df, day, SELL_IST)
        if at is None:
            continue
        p = snap[(snap["type"] == "P") & (snap["series"] == "monthly")].dropna(subset=["delta"])
        if p.empty:
            continue
        for target in PUT_DELTAS:
            r = p.loc[(p["delta"] - target).abs().idxmin()]
            out.append({"day": day, "target_delta": target, "symbol": r["symbol"], "delta": r["delta"],
                        "strike": r["strike"], "pct_below_spot": round((1 - r["strike"] / r["spot"]) * 100, 2),
                        "ask": r["usable_ask"], "bid": r["usable_bid"], "mark": r["mark"],
                        "ask_pct_of_spot": round(r["usable_ask"] / r["spot"] * 100, 3) if pd.notna(r["usable_ask"]) else None,
                        "days_to_expiry": round(r["minutes_to_expiry"] / 1440, 1)})
    return pd.DataFrame(out)


def md_table(frame):
    """DataFrame -> markdown table (no extra package needed)."""
    if frame.empty:
        return "(none)"
    cols = [str(c) for c in frame.columns]
    fmt = lambda v: "" if pd.isna(v) else (f"{v:.4g}" if isinstance(v, float) else str(v))
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=HERE, help="repository copy to read (default: this script's folder)")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--out", default=os.path.join(HERE, "reports"))
    a = ap.parse_args()

    df = load(a.root, a.start, a.end)
    sells, trips = sells_and_roundtrips(df)
    sp, pt = spreads(df), puts(df)
    os.makedirs(a.out, exist_ok=True)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M")
    for name, frame in (("sells", sells), ("roundtrip", trips), ("spreads", sp), ("puts", pt)):
        frame.to_csv(os.path.join(a.out, f"{name}_{stamp}.csv"), index=False)

    days = sorted(df["day_ist"].unique())
    md = [f"# BTC option quote report ({days[0]} to {days[-1]} IST)", "",
          f"{df['ts_utc'].nunique()} snapshots, {len(df):,} rows.", "",
          "## 1-2. Daily delta-0.03 call: sell 17:35 IST, buy back next day 17:20-17:29 IST", ""]
    if not trips.empty and "net_per_lot_usd_ask_median" in trips:
        done = trips.dropna(subset=["net_per_lot_usd_ask_median"])
        md += [f"Complete round trips: {len(done)}. Net per lot (0.001 BTC) after fees, buying back at the median ask: "
               f"mean {done['net_per_lot_usd_ask_median'].mean():.4f} USD, median {done['net_per_lot_usd_ask_median'].median():.4f} USD, "
               f"total {done['net_per_lot_usd_ask_median'].sum():.4f} USD.", ""]
    md += [md_table(sells), "",
           md_table(trips), "",
           "## 3. Median spread % of mark (all hours)", ""]
    if not sp.empty:
        o = sp.groupby(["series", "type", "bucket"]).apply(
            lambda g: pd.Series({"median": (g["median"] * g["n"]).sum() / g["n"].sum(), "n": g["n"].sum()}),
            include_groups=False).round(2).reset_index()
        md += ["(n-weighted average of the hourly medians; per-hour detail in spreads CSV)", "", md_table(o), ""]
    md += ["## 4. Monthly protective puts at 17:35 IST", "", md_table(pt), ""]
    path = os.path.join(a.out, f"summary_{stamp}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("\n".join(md[:8]))
    print(f"\nwritten: {a.out}\\*_{stamp}.*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
