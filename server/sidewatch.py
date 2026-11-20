#!/usr/bin/env python3
"""sidewatch (20-Nov-2026, Sudip): collect the live evidence for two PARKED ideas so they can be decided later:
  idea 2 - separate size multipliers for PUT nights and CALL nights   (re-check after 1-2 years live)
  idea 3 - separate capital per 0.01 for PUT nights and CALL nights  (re-check after months live / a real 8 % move)
READ ONLY. Places no orders, changes no bot file. Run by cron at 17:45 IST (after the 17:20 exit).

Per night it writes one row to logs/sidewatch_nights.csv:
  - BTC overnight path 23:30 -> 17:20 from the option-book recorder's spot (every night, traded or not):
    worst fall and worst rise in %, so big moves on SKIPPED nights are also kept
  - from logs/nightlive_margin.csv (minute rows while a sale is open): per side (PUT / CALL) contracts sold,
    hedge contracts held, worst net open loss in USD and per 0.01 BTC sold, worst move against that side,
    and the account's peak money tied up that night
  - farthest listed put and call strike at 23:30 (from the option-book recorder) = whether a far strike existed
A TRIGGER alert (Telegram + e-mail) goes out when BTC moved 8 % or more against either side overnight,
because that is the re-check trigger written in the parked docs.
  venv/bin/python sidewatch.py            process every finished night not yet in the CSV
  venv/bin/python sidewatch.py --dry      print only, write nothing, send nothing"""
import csv, glob, gzip, json, os, re, sys, datetime as dt

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
MARGIN = os.path.join(HOME, "logs", "nightlive_margin.csv")
OPTB = os.path.join(HOME, "optbook")
OUT = os.path.join(HOME, "logs", "sidewatch_nights.csv")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TRIGGER = 8.0
POS = re.compile(r"([CP])-BTC-(\d+)-\d+:(-?\d+)@([\d.]+) mark ([\d.]+)")
COLS = ["night", "spot_2330", "worst_fall_pct", "worst_rise_pct", "farthest_put_pct", "farthest_call_pct",
        "put_sold", "put_hedge", "put_worst_ol_usd", "put_ol_per_001", "put_move_against_pct",
        "call_sold", "call_hedge", "call_worst_ol_usd", "call_ol_per_001", "call_move_against_pct",
        "peak_tied_usd", "trigger"]


def spot_path(night):
    """(t, spot) from optbook lines between 23:30 IST of `night` and 17:20 IST next day; plus first-snapshot strikes."""
    a = dt.datetime.combine(night, dt.time(23, 30), IST).timestamp()
    b = a + 17 * 3600 + 50 * 60
    pts, strikes, first_t = [], {"C": [], "P": []}, None
    days = {night, night + dt.timedelta(days=1)}
    for f in sorted(glob.glob(os.path.join(OPTB, "*.jsonl*"))):
        try:
            if dt.datetime.strptime(os.path.basename(f)[:8], "%Y%m%d").date() not in days:
                continue
        except Exception:
            continue
        op = gzip.open if f.endswith(".gz") else open
        try:
            with op(f, "rt") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    t = r.get("t", 0)
                    if not (a - 120 <= t <= b):
                        continue
                    sp = r.get("sp")
                    if sp:
                        pts.append((t, float(sp)))
                    if t <= a + 600 and r.get("ty") in ("C", "P"):
                        strikes[r["ty"]].append((float(r["k"]), float(sp or 0)))
        except Exception:
            continue
    pts.sort()
    return pts, strikes


def margin_rows(night):
    if not os.path.exists(MARGIN):
        return []
    a = dt.datetime.combine(night, dt.time(23, 0))
    b = a + dt.timedelta(hours=18, minutes=30)
    out = []
    for r in csv.DictReader(open(MARGIN)):
        try:
            t = dt.datetime.strptime(r["time_ist"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if a <= t <= b:
            out.append((t, r))
    return out


def one_night(night):
    pts, strikes = spot_path(night)
    rows = margin_rows(night)
    if not pts and not rows:
        return None
    s0 = pts[0][1] if pts else float(rows[0][1]["spot"])
    sp = [p for _, p in pts] or [float(r["spot"]) for _, r in rows]
    fall = max(0.0, (s0 - min(sp)) / s0 * 100)
    rise = max(0.0, (max(sp) - s0) / s0 * 100)
    fp = min((k for k, _ in strikes["P"]), default=None)
    fc = max((k for k, _ in strikes["C"]), default=None)
    rec = dict(night=night.isoformat(), spot_2330=round(s0, 1), worst_fall_pct=round(fall, 2), worst_rise_pct=round(rise, 2),
               farthest_put_pct=round((s0 - fp) / s0 * 100, 2) if fp else "", farthest_call_pct=round((fc - s0) / s0 * 100, 2) if fc else "")
    side = {"P": dict(sold=0, hedge=0, ol=0.0, sale=None, adv=0.0), "C": dict(sold=0, hedge=0, ol=0.0, sale=None, adv=0.0)}
    peak = 0.0
    for t, r in rows:
        try:
            spot = float(r["spot"]); peak = max(peak, float(r["tied_up_usd"] or 0))
        except Exception:
            continue
        net = {"P": 0.0, "C": 0.0}
        seen = {"P": False, "C": False}
        for ty, k, size, entry, mark in POS.findall(r.get("positions", "")):
            size, entry, mark = int(size), float(entry), float(mark)
            d = side[ty]; seen[ty] = True
            if size < 0:
                d["sold"] = max(d["sold"], -size)
                if d["sale"] is None:
                    d["sale"] = spot
            else:
                d["hedge"] = max(d["hedge"], size)
            net[ty] += (mark - entry) * size * 0.001        # USD; short loses when mark rises
        for ty in "PC":
            if seen[ty]:
                side[ty]["ol"] = min(side[ty]["ol"], net[ty])
                s = side[ty]["sale"]
                if s:
                    adv = (s - spot) / s * 100 if ty == "P" else (spot - s) / s * 100
                    side[ty]["adv"] = max(side[ty]["adv"], adv)
    for ty, nm in (("P", "put"), ("C", "call")):
        d = side[ty]
        ol = max(0.0, -d["ol"])
        rec.update({nm + "_sold": d["sold"], nm + "_hedge": d["hedge"], nm + "_worst_ol_usd": round(ol, 2),
                    nm + "_ol_per_001": round(ol / (d["sold"] / 10.0), 2) if d["sold"] else "",
                    nm + "_move_against_pct": round(d["adv"], 2) if d["sold"] else ""})
    rec["peak_tied_usd"] = round(peak, 2)
    trig = []
    if fall >= TRIGGER:
        trig.append("fall %.1f%%" % fall)
    if rise >= TRIGGER:
        trig.append("rise %.1f%%" % rise)
    rec["trigger"] = " ".join(trig)
    return rec


def done_nights():
    if not os.path.exists(OUT):
        return set()
    return {r["night"] for r in csv.DictReader(open(OUT))}


def main():
    dry = "--dry" in sys.argv
    now = dt.datetime.now(IST)
    last = (now - dt.timedelta(hours=17, minutes=40)).date() - dt.timedelta(days=1)   # newest finished night
    have = done_nights()
    first = last - dt.timedelta(days=30)
    new = []
    d = first
    while d <= last:
        if d.isoformat() not in have:
            r = one_night(d)
            if r:
                new.append(r)
        d += dt.timedelta(days=1)
    for r in new:
        print(json.dumps(r))
    if dry or not new:
        print("sidewatch: %d new night(s)%s" % (len(new), " (dry run)" if dry else ""))
        return
    hdr = not os.path.exists(OUT)
    with open(OUT, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        if hdr:
            w.writeheader()
        w.writerows(new)
    trig = [r for r in new if r["trigger"]]
    if trig:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(HOME, ".env"))
            sys.path.insert(0, HOME)
            import bot
            body = "\n".join("night %s: %s (put open loss %s USD, call open loss %s USD). Farthest put listed %s%% below, call %s%% above."
                             % (r["night"], r["trigger"], r["put_worst_ol_usd"], r["call_worst_ol_usd"], r["farthest_put_pct"], r["farthest_call_pct"]) for r in trig)
            bot.Notifier()._send_now("[DeltaBot] SIDEWATCH TRIGGER - 8%+ overnight move", body +
                                     "\nThis is the re-check trigger for the parked put/call sizing and capital-per-side ideas. Ask Claude to review.")
        except Exception as e:
            print("alert failed:", e)
    print("sidewatch: wrote %d night(s), %d trigger(s)" % (len(new), len(trig)))


if __name__ == "__main__":
    main()
