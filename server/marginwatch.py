"""6-Nov-2026 (Sudip): watch how much margin the live night sell really blocks on every adverse BTC move -
the key number for upsizing the night base. Read-only. Source: logs/nightlive_margin.csv (one row per minute while
a sale is open, written by nightlive). Per night: contracts sold, side, spot at sale, worst move AGAINST the sale,
peak money tied up (balance - available), and that peak per 0.01 BTC sold and as % of balance.
7-Nov-2026 additions (Sudip: "keep collecting data for more precision"): worst open (unrealised) loss per night and per
0.01 BTC sold, peak margin as % of notional sold, and the closest distance of spot to Delta's liquidation price.
Then: what a 3 x base night would tie up at the bases 0.04..0.07 for the worst move seen so far.
  venv/bin/python marginwatch.py         print + write logs/marginwatch_nights.csv"""
import csv, os, re, sys, datetime as dt, collections
HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
SRC = os.path.join(HOME, "logs", "nightlive_margin.csv")
OUT = os.path.join(HOME, "logs", "marginwatch_nights.csv")


def night_of(t):
    """a sale at 23:30 belongs to that date; rows until the next 17:30 too"""
    return (t - dt.timedelta(hours=17, minutes=31)).date()


def nights():
    if not os.path.exists(SRC):
        return []
    N = collections.OrderedDict()
    for r in csv.DictReader(open(SRC)):
        try:
            t = dt.datetime.strptime(r["time_ist"], "%Y-%m-%d %H:%M:%S")
            spot = float(r["spot"]); tied = float(r["tied_up_usd"]); bal = float(r["wallet_balance"])
            unr = float(r.get("unrealised_pnl_usd") or 0)
        except Exception:
            continue
        legs = re.findall(r"([CP])-BTC-(\d+)-\d+:(-?\d+)@", r.get("positions", ""))
        short = sum(-int(q) for s, k, q in legs if int(q) < 0)
        side = legs[0][0] if legs else "?"
        n = N.setdefault(night_of(t), dict(rows=0, spot0=spot, side=side, sold=0, peak=0.0, bal=bal, worst=0.0, worst_spot=spot, t_peak="",
                                            unr=0.0, liq=None))
        n["unr"] = min(n["unr"], unr)
        for lq in re.findall(r"liq ([0-9.]+)", r.get("positions", "")):
            try:
                dd = abs(float(lq) / spot - 1) * 100
                if float(lq) > 0 and (n["liq"] is None or dd < n["liq"]):
                    n["liq"] = dd
            except ValueError:
                pass
        n["rows"] += 1
        n["sold"] = max(n["sold"], short)
        mv = (spot / n["spot0"] - 1) * (1 if n["side"] == "C" else -1)   # + = against the sale
        if mv > n["worst"]:
            n["worst"], n["worst_spot"] = mv, spot
        if tied > n["peak"]:
            n["peak"], n["t_peak"], n["bal"] = tied, t.strftime("%d-%b %H:%M"), bal
    out = []
    for d, n in N.items():
        if not n["sold"]:
            continue
        per = n["peak"] / (n["sold"] / 10.0)            # USD per 0.01 BTC (10 contracts)
        out.append(dict(night=str(d), side="PUT" if n["side"] == "P" else "CALL", sold_btc=n["sold"] / 1000, spot_at_sale=round(n["spot0"]),
                        worst_move_against_pct=round(100 * n["worst"], 2), peak_tied_usd=round(n["peak"], 2), peak_at=n["t_peak"],
                        peak_per_001_usd=round(per, 2), peak_pct_balance=round(100 * n["peak"] / n["bal"], 2) if n["bal"] else 0,
                        worst_open_loss_usd=round(-n["unr"], 2), worst_open_loss_per_001_usd=round(-n["unr"] / (n["sold"] / 10.0), 2),
                        peak_margin_pct_notional=round(100 * n["peak"] / (n["sold"] / 1000 * n["spot0"]), 2),
                        closest_liq_pct=round(n["liq"], 1) if n["liq"] is not None else ""))
    return out


def summary():
    R = nights()
    if not R:
        return "Margin watch: no live night with an open sale logged yet."
    L = ["Margin watch (real Delta margin while the night sale was open):",
         "night | side | sold BTC | worst move against | peak tied USD | per 0.01 BTC | % of balance | margin % notional | worst open loss USD | spot-to-liq closest"]
    for r in R[-10:]:
        L.append("%s | %s | %.3f | %.2f %% | %.2f | %.2f | %.2f %% | %.2f %% | %.2f | %s" % (r["night"], r["side"], r["sold_btc"], r["worst_move_against_pct"],
                                                                     r["peak_tied_usd"], r["peak_per_001_usd"], r["peak_pct_balance"],
                                                                     r["peak_margin_pct_notional"], r["worst_open_loss_usd"],
                                                                     ("%s %%" % r["closest_liq_pct"]) if r["closest_liq_pct"] != "" else "n/a"))
    w = max(R, key=lambda r: r["peak_per_001_usd"])
    L.append("Highest so far: %.2f USD tied per 0.01 BTC sold (night %s, move against %.2f %%)." % (w["peak_per_001_usd"], w["night"], w["worst_move_against_pct"]))
    L.append("If a 3 x night hit that same move: base 0.04 -> %.0f USD, 0.05 -> %.0f, 0.06 -> %.0f, 0.07 -> %.0f USD tied." % tuple(
        w["peak_per_001_usd"] * 3 * b * 100 for b in (0.04, 0.05, 0.06, 0.07)))
    L.append("Highest margin seen: %.2f %% of notional sold (safe-balance rule assumes 5 %% - lower it only after many rough nights)." % max(r["peak_margin_pct_notional"] for r in R))
    L.append("Worst move against seen so far: %.2f %% (a 40 %% crash is far beyond this sample - keep the crash reserve rule)." % max(r["worst_move_against_pct"] for r in R))
    return "\n".join(L)


if __name__ == "__main__":
    R = nights()
    if R:
        with open(OUT, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(R[0])); w.writeheader(); w.writerows(R)
    print(summary())
