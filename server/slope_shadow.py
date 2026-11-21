#!/usr/bin/env python3
"""SMA100-slope SHADOW recorder for the v15 extra call (public data only: no API key, never places an order,
never touches the trading bot or its files except READING ~/deltabot/logs/calls_lv15.csv for the report).

What it does
  run     once a UTC day (from 12:00 UTC = 17:30 IST, the moment v15 sizes its extra call) it reads Delta's public
          daily BTCUSD candles and records: previous completed close, SMA100, "below SMA100" flag, the SMA100 slope
          (percent change of the SMA100 over n days, n = 3 5 7 10 14 21 30) and, for each shadow rule, the
          multiplier / cap the rule WOULD use.  Appends one row to ~/deltabot/slope_shadow/daily_slopes.csv.
  once    prints today's row without writing anything.
  report  joins the recorded rows with v15's own call log (calls_lv15.csv) and prints, per day and in total, what the
          real v15 extra call earned and what each shadow rule would have earned (same profit per contract, shadow size).
Rules live in ~/deltabot/slope_shadow/rules.json (created with defaults on first run; edit any time, re-read each day).
Slope definition = backtest definition: SMA100 of the last 100 COMPLETED daily closes (UTC days), compared with the
same SMA100 n daily bars earlier.  slope_n = (SMA_now / SMA_n_bars_ago - 1) * 100."""
import csv, datetime as dt, json, os, socket, sys, time, urllib.request, glob

_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
OUT = os.path.join(HOME, "slope_shadow")
DAILY = os.path.join(OUT, "daily_slopes.csv")
RULES_F = os.path.join(OUT, "rules.json")
CALLS = os.path.join(HOME, "logs", os.environ.get("SS_CALLS", "calls_lv15.csv"))
URL = "https://api.india.delta.exchange/v2/history/candles?resolution=1d&symbol=BTCUSD&start=%d&end=%d"
SLOPES = [3, 5, 7, 10, 14, 21, 30]
SMA_N = 100
RECORD_FROM_UTC_HOUR = 12
C = 0.001          # BTC per contract
V15_XMUL, V15_XMAX = 5.0, 0.3     # only used to label the report; the real v15 numbers come from its own log

# Thresholds = quantiles of the SMA100 slope on the 389 extra-call days of the 2020-2026 test (percent).
# "mirror" rules: bigger size only when the slope is NOT falling fast (slope >= thr).  "fall" = control (the idea first asked).
DEFAULT_RULES = [
    {"name": "mirror21_top70_6x08", "n": 21, "op": ">=", "thr": -6.70, "m": 6, "cap": 0.8},
    {"name": "mirror21_top70_5x05", "n": 21, "op": ">=", "thr": -6.70, "m": 5, "cap": 0.5},
    {"name": "mirror10_top80_6x08", "n": 10, "op": ">=", "thr": -4.19, "m": 6, "cap": 0.8},
    {"name": "mirror10_top80_5x05", "n": 10, "op": ">=", "thr": -4.19, "m": 5, "cap": 0.5},
    {"name": "mirror5_top80_6x08",  "n": 5,  "op": ">=", "thr": -2.17, "m": 6, "cap": 0.8},
    {"name": "fall21_bot30_6x08",   "n": 21, "op": "<=", "thr": -6.70, "m": 6, "cap": 0.8},
]


def load_rules():
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(RULES_F):
        json.dump(DEFAULT_RULES, open(RULES_F, "w"), indent=1)
    try:
        r = json.load(open(RULES_F))
        assert isinstance(r, list) and all({"name", "n", "op", "thr", "m", "cap"} <= set(x) for x in r)
        return r
    except Exception:
        return DEFAULT_RULES


def fetch_closes(now_ts, candles_file=None):
    """completed daily closes (UTC), oldest first: list of (day_start_ts, close)."""
    day0 = int(now_ts // 86400) * 86400
    if candles_file:                       # test mode: CSV with columns date,close (UTC dates)
        rows = []
        for r in csv.DictReader(open(candles_file)):
            t = int(dt.datetime.strptime(r["date"][:10], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())
            rows.append((t, float(r["close"])))
    else:
        req = urllib.request.Request(URL % (day0 - 260 * 86400, day0 + 86400), headers={"User-Agent": "slope-shadow/1"})
        res = json.load(urllib.request.urlopen(req, timeout=20))["result"]
        rows = [(int(x["time"]), float(x["close"])) for x in res]
    rows = sorted(set(rows))
    return [r for r in rows if r[0] < day0]          # Delta pads a future/partial candle: keep completed days only


def sma(vals, back=0):
    seg = vals[len(vals) - SMA_N - back: len(vals) - back]
    return sum(seg) / len(seg) if len(seg) == SMA_N else None


def snapshot(now_ts, rules, candles_file=None):
    cl = fetch_closes(now_ts, candles_file)
    closes = [c for _, c in cl]
    if len(closes) < SMA_N + max(SLOPES) + 1:
        raise RuntimeError("only %d completed daily candles" % len(closes))
    s0 = sma(closes)
    pc = closes[-1]
    row = {"date_utc": dt.datetime.fromtimestamp(now_ts, dt.timezone.utc).strftime("%Y-%m-%d"),
           "t_utc": dt.datetime.fromtimestamp(now_ts, dt.timezone.utc).strftime("%H:%M:%S"),
           "prev_close": round(pc, 2), "sma100": round(s0, 2), "below_sma": int(pc <= s0)}
    sl = {}
    for n in SLOPES:
        sn = sma(closes, n)
        sl[n] = (s0 / sn - 1) * 100
        row["s%d" % n] = round(sl[n], 3)
    for r in rules:
        v = sl.get(r["n"])
        if v is None:
            on = 0
        else:
            on = int(v >= r["thr"]) if r["op"] == ">=" else int(v <= r["thr"])
        row[r["name"] + "_on"] = on
        row[r["name"] + "_m"] = r["m"] if on else ""
        row[r["name"] + "_cap"] = r["cap"] if on else ""
    return row


def append_row(row):
    os.makedirs(OUT, exist_ok=True)
    new = not os.path.exists(DAILY)
    cols = list(row)
    if not new:
        with open(DAILY) as fh:
            old = next(csv.reader(fh), [])
        if old != cols:        # rules changed: start a new file generation, keep the old one
            os.replace(DAILY, DAILY + ".%s.old" % time.strftime("%Y%m%d%H%M%S"))
            new = True
    with open(DAILY, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(cols)
        w.writerow([row[c] for c in cols])


def recorded_dates():
    out = set()
    for f in glob.glob(DAILY + "*"):
        try:
            for r in csv.DictReader(open(f)):
                out.add(r["date_utc"])
        except Exception:
            pass
    return out


def run_loop():
    print("slope_shadow running; out", OUT, flush=True)
    while True:
        try:
            now = time.time()
            u = dt.datetime.fromtimestamp(now, dt.timezone.utc)
            day = u.strftime("%Y-%m-%d")
            if u.hour >= RECORD_FROM_UTC_HOUR and day not in recorded_dates():
                row = snapshot(now, load_rules())
                if day not in recorded_dates():
                    append_row(row)
                    print("recorded", day, "slope10 %.2f slope21 %.2f below=%d" % (row["s10"], row["s21"], row["below_sma"]), flush=True)
        except Exception as e:
            print("error", repr(e), flush=True)
        try:
            open(os.path.join(OUT, "heartbeat"), "w").write(str(int(time.time())))
        except Exception:
            pass
        time.sleep(300)


# ------------------------------------------------------------------------------------------------ report
def read_calls():
    """returns {ist_date: dict(cov=contracts, x=contracts, pnl=usd, syms=set)} for extra calls (kinds x, x2) and covered."""
    days, sold_sym = {}, {}
    if not os.path.exists(CALLS):
        return days
    rows = list(csv.DictReader(open(CALLS)))
    for r in rows:
        if r["event"] == "SELL":
            d = r["time_ist"][:10]
            e = days.setdefault(d, dict(cov=0, x=0, pnl=0.0, fee=0.0))
            c = int(float(r["contracts"]))
            if r["kind"] == "cov":
                e["cov"] += c
            elif r["kind"] in ("x", "x2"):
                e["x"] += c
                sold_sym[(r["symbol"], r["kind"])] = d
    for r in rows:                                                 # closing rows of extra calls -> profit of the day sold
        if r["event"].startswith(("BUYBACK", "SETTLE")) and r["kind"] in ("x", "x2"):
            d = sold_sym.get((r["symbol"], r["kind"]))
            if d:
                days[d]["pnl"] += float(r["pnl_usd"])
    return days


def settled(days_entry, d, today_ist):
    return d < today_ist


def report():
    rules = load_rules()
    rows = []
    for f in sorted(glob.glob(DAILY + "*")):
        try:
            rows += list(csv.DictReader(open(f)))
        except Exception:
            pass
    by = {r["date_utc"]: r for r in rows}
    calls = read_calls()
    now_ist = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    tot = {"days": 0, "act_x": 0, "act_pnl": 0.0}
    sh = {r["name"]: dict(days=0, on=0, qty=0, pnl=0.0, d_pnl=0.0) for r in rules}
    print("%-10s %6s %6s %7s %7s %7s %8s" % ("date", "slope10", "slope21", "cov_c", "xtra_c", "pnl_$", "$/contract"))
    for d in sorted(calls):
        e = calls[d]
        r = by.get(d)
        if e["x"] <= 0 or d >= now_ist or r is None:
            continue
        u = e["pnl"] / e["x"]
        tot["days"] += 1; tot["act_x"] += e["x"]; tot["act_pnl"] += e["pnl"]
        print("%-10s %7s %7s %7d %7d %7.2f %8.3f" % (d, r["s10"], r["s21"], e["cov"], e["x"], e["pnl"], u))
        for ru in rules:
            on = r.get(ru["name"] + "_on") == "1"
            if on:
                q = min(int((ru["m"] - 1) * e["cov"]), int(round(ru["cap"] / C)))
            else:
                q = e["x"]          # rule off: shadow = what v15 really did that day
            s = sh[ru["name"]]
            s["days"] += 1; s["on"] += int(on); s["qty"] += q; s["pnl"] += u * q; s["d_pnl"] += u * q - e["pnl"]
    print("\nreal v15 extra calls: %d days, %d contracts, %.2f USD" % (tot["days"], tot["act_x"], tot["act_pnl"]))
    print("%-24s %5s %5s %9s %10s %9s" % ("shadow rule", "days", "on", "shadow_$", "vs real_$", "contracts"))
    for ru in rules:
        s = sh[ru["name"]]
        print("%-24s %5d %5d %9.2f %+10.2f %9d" % (ru["name"], s["days"], s["on"], s["pnl"], s["d_pnl"], s["qty"]))
    print("(shadow = same profit per contract as the real call that day, resized by the rule; rule 'off' = real size. "
          "Evidence needs losing days: look at the bad days, not the total.)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    cf = os.environ.get("SS_CANDLES_FILE")
    if cmd == "run":
        run_loop()
    elif cmd == "once":
        print(json.dumps(snapshot(time.time(), load_rules(), cf), indent=1))
    elif cmd == "report":
        report()
    else:
        print(__doc__)
