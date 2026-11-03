"""Funding logger (3-Nov-2026). READ-ONLY - never places orders. Service "fundlog", once an hour:
 1. public BTCUSD ticker          -> logs/funding_rate.csv      (utc, mark, funding_rate in % per 8 h)
 2. real funding paid/received    -> logs/funding_<acct>.csv    for every Delta account whose keys are on the server
                                     (wallet transactions of type "funding"; amount < 0 = we paid, > 0 = we received)
 3. state/funding_summary.json    -> shown on the control page at /funding
Delta BTCUSD facts (product spec 3-Nov-2026): rate quoted per 8 h (rate_exchange_interval 28800), exchanged every minute,
annualized_funding cap 10.95 % = 0.01 %/8 h = 0.03 %/day. The backtest engine's constant 0.01 %/8 h is therefore the WORST case.
Usage:  venv/bin/python fundlog.py            (service loop)      venv/bin/python fundlog.py --once   (one pass, prints summary)
"""
import os, sys, json, csv, time, logging, datetime as dt
from logging.handlers import RotatingFileHandler
import requests

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
LOGS = os.path.join(HOME, "logs"); STATE = os.path.join(HOME, "state")
API = "https://api.india.delta.exchange"
ACCTS = ("ladder9", "serverbot", "main")
RATE_CSV = os.path.join(LOGS, "funding_rate.csv")
SUMMARY = os.path.join(STATE, "funding_summary.json")
ST = os.path.join(STATE, "fundlog.json")
CAP = 0.01   # % per 8 h

log = logging.getLogger("fundlog")


def setup_log():
    os.makedirs(LOGS, exist_ok=True); os.makedirs(STATE, exist_ok=True)
    h = RotatingFileHandler(os.path.join(LOGS, "fundlog.log"), maxBytes=2_000_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h); log.addHandler(logging.StreamHandler(sys.stdout)); log.setLevel(logging.INFO)


def load_state():
    try:
        return json.load(open(ST))
    except Exception:
        return {}


def save_state(s):
    tmp = ST + ".tmp"; json.dump(s, open(tmp, "w")); os.replace(tmp, ST)


def append_csv(path, header, rows):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------- 1. public rate
def log_rate():
    r = requests.get(API + "/v2/tickers/BTCUSD", timeout=15).json()["result"]
    rate = float(r.get("funding_rate") or 0.0); mark = float(r.get("mark_price") or 0.0)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    append_csv(RATE_CSV, ["utc", "mark", "funding_rate_pct_8h"], [[now.isoformat(), "%.2f" % mark, "%.5f" % rate]])
    log.info("rate %.5f %%/8h  mark %.1f", rate, mark)
    return rate, mark


# ---------------------------------------------------------------- 2. real funding per account
def parse_ts(s):
    s = str(s).replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return dt.datetime.fromtimestamp(float(s) / 1e6, dt.timezone.utc)


def fetch_funding(acct, state):
    import liveorders as LO
    cl = LO.Live(acct)
    st = state.setdefault(acct, {"last_us": int((time.time() - 30 * 86400) * 1e6), "ids": []})
    seen = set(st.get("ids", []))
    params = {"transaction_types": "funding", "page_size": 100, "start_time": int(st["last_us"]) + 1}
    rows, pages = [], 0
    while True:
        res = cl._p("GET", "/v2/wallet/transactions", params)
        for x in res.get("result") or []:
            if x.get("id") in seen:
                continue
            t = parse_ts(x.get("created_at")); us = int(t.timestamp() * 1e6)
            md = x.get("meta_data") or {}
            rows.append([t.isoformat(), x.get("amount"), x.get("balance"), x.get("product_id"), x.get("asset_symbol"),
                         md.get("product_symbol", ""), x.get("id")])
            seen.add(x.get("id")); st["last_us"] = max(int(st["last_us"]), us)
        after = (res.get("meta") or {}).get("after"); pages += 1
        if not after or pages > 50:
            break
        params["after"] = after
    if rows:
        rows.sort()
        append_csv(os.path.join(LOGS, "funding_%s.csv" % acct), ["utc", "amount_usd", "balance_usd", "product_id", "asset", "symbol", "txn_id"], rows)
    st["ids"] = sorted(seen, key=lambda v: str(v))[-2000:]
    log.info("%s: %d new funding transactions", acct, len(rows))
    return len(rows)


# ---------------------------------------------------------------- 3. summary
def read_csv(path):
    try:
        with open(path) as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def summarize():
    now = dt.datetime.now(dt.timezone.utc)
    S = {"updated_utc": now.replace(microsecond=0).isoformat(), "cap_pct_8h": CAP, "rate": {}, "accounts": {}}
    R = read_csv(RATE_CSV)
    for r in R:
        r["_t"] = parse_ts(r["utc"]); r["_v"] = float(r["funding_rate_pct_8h"])
    if R:
        S["rate"]["now_pct_8h"] = R[-1]["_v"]; S["rate"]["now_utc"] = R[-1]["utc"]; S["rate"]["mark"] = float(R[-1]["mark"])
    for lab, days in (("24h", 1), ("7d", 7), ("30d", 30)):
        v = [r["_v"] for r in R if r["_t"] >= now - dt.timedelta(days=days)]
        if v:
            m = sum(v) / len(v)
            S["rate"][lab] = {"mean_pct_8h": round(m, 5), "mean_pct_day": round(3 * m, 5), "annualised_pct": round(m * 3 * 365, 2),
                              "share_negative": round(sum(1 for x in v if x < 0) / len(v), 3), "share_at_cap": round(sum(1 for x in v if x >= CAP - 1e-9) / len(v), 3),
                              "samples": len(v)}
    # daily table (last 30 days)
    byday = {}
    for r in R:
        byday.setdefault(r["_t"].date().isoformat(), []).append(r["_v"])
    S["rate"]["daily"] = [{"day": d, "mean_pct_8h": round(sum(v) / len(v), 5), "min": round(min(v), 5), "max": round(max(v), 5), "n": len(v)}
                          for d, v in sorted(byday.items())[-30:]]
    for acct in ACCTS:
        T = read_csv(os.path.join(LOGS, "funding_%s.csv" % acct))
        if not T:
            continue
        for r in T:
            r["_t"] = parse_ts(r["utc"]); r["_a"] = float(r["amount_usd"] or 0)
        A = {"transactions": len(T), "first_utc": T[0]["utc"], "last_utc": T[-1]["utc"]}
        for lab, days in (("24h", 1), ("7d", 7), ("30d", 30), ("all", 10000)):
            v = [r["_a"] for r in T if r["_t"] >= now - dt.timedelta(days=days)]
            A[lab] = {"net_usd": round(sum(v), 4), "paid_usd": round(-sum(x for x in v if x < 0), 4), "received_usd": round(sum(x for x in v if x > 0), 4), "n": len(v)}
        dd = {}
        for r in T:
            dd[r["_t"].date().isoformat()] = dd.get(r["_t"].date().isoformat(), 0.0) + r["_a"]
        A["daily"] = [{"day": d, "net_usd": round(v, 4)} for d, v in sorted(dd.items())[-30:]]
        S["accounts"][acct] = A
    tmp = SUMMARY + ".tmp"; json.dump(S, open(tmp, "w"), indent=1); os.replace(tmp, SUMMARY)
    return S


def one_pass():
    try:
        log_rate()
    except Exception as e:
        log.error("rate: %s", e)
    state = load_state()
    for acct in ACCTS:
        try:
            fetch_funding(acct, state)
        except Exception as e:
            log.warning("%s: funding read skipped (%s)", acct, str(e)[:160])
    save_state(state)
    return summarize()


def page_html():
    try:
        S = json.load(open(SUMMARY))
    except Exception:
        S = {}
    R = S.get("rate", {}); h = []
    h.append('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>Funding</title><style>body{font-family:system-ui,sans-serif;margin:12px;max-width:900px}table{border-collapse:collapse;font-size:13px}'
             'td,th{border:1px solid #ddd;padding:4px 8px;text-align:right}th{background:#f1f5f9}td:first-child,th:first-child{text-align:left}'
             '.box{background:#fef3c7;border-radius:8px;padding:8px 12px;margin:8px 0}.neg{color:#b91c1c}.pos{color:#15803d}</style></head><body>')
    h.append('<p><a href="/">&larr; Control page</a></p><h2>BTCUSD funding (Delta India)</h2>')
    h.append('<div class="box">Rate is per 8 hours, exchanged every minute; longs pay when positive. Cap 0.01 %%/8 h = 0.03 %%/day = 10.95 %%/yr '
             '(the backtests assume this worst case all the time). Updated %s UTC.</div>' % S.get("updated_utc", "-"))
    if R:
        h.append('<p><b>Now: %.5f %% / 8 h</b> (mark %.0f, %s)</p>' % (R.get("now_pct_8h", 0), R.get("mark", 0), R.get("now_utc", "")))
        h.append('<table><tr><th>window</th><th>mean %/8h</th><th>%/day</th><th>%/year</th><th>time negative</th><th>time at cap</th><th>samples</th></tr>')
        for lab in ("24h", "7d", "30d"):
            x = R.get(lab)
            if x:
                h.append('<tr><td>%s</td><td>%.5f</td><td>%.4f</td><td>%.2f</td><td>%.0f%%</td><td>%.0f%%</td><td>%d</td></tr>' % (
                    lab, x["mean_pct_8h"], x["mean_pct_day"], x["annualised_pct"], 100 * x["share_negative"], 100 * x["share_at_cap"], x["samples"]))
        h.append('</table>')
    for acct, A in (S.get("accounts") or {}).items():
        h.append('<h3>Account %s - real funding (USD)</h3><table><tr><th>window</th><th>paid</th><th>received</th><th>net</th><th>payments</th></tr>' % acct)
        for lab in ("24h", "7d", "30d", "all"):
            x = A.get(lab)
            if x:
                cls = "neg" if x["net_usd"] < 0 else "pos"
                h.append('<tr><td>%s</td><td>%.4f</td><td>%.4f</td><td class="%s">%+.4f</td><td>%d</td></tr>' % (lab, x["paid_usd"], x["received_usd"], cls, x["net_usd"], x["n"]))
        h.append('</table><details><summary>daily net (last 30 days)</summary><table><tr><th>day</th><th>net USD</th></tr>')
        for d in A.get("daily", []):
            h.append('<tr><td>%s</td><td class="%s">%+.4f</td></tr>' % (d["day"], "neg" if d["net_usd"] < 0 else "pos", d["net_usd"]))
        h.append('</table></details>')
    if R.get("daily"):
        h.append('<h3>Rate by day (mean / min / max, %% per 8 h)</h3><table><tr><th>day</th><th>mean</th><th>min</th><th>max</th><th>n</th></tr>')
        for d in R["daily"][::-1]:
            h.append('<tr><td>%s</td><td class="%s">%.5f</td><td>%.5f</td><td>%.5f</td><td>%d</td></tr>' % (d["day"], "neg" if d["mean_pct_8h"] < 0 else "", d["mean_pct_8h"], d["min"], d["max"], d["n"]))
        h.append('</table>')
    h.append('<p style="color:#64748b;font-size:12px">Files: logs/funding_rate.csv, logs/funding_&lt;account&gt;.csv (read-only logger, service fundlog).</p></body></html>')
    return "".join(h).encode("utf-8")


def main():
    setup_log()
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HOME, ".env"))
    except Exception:
        pass
    if "--once" in sys.argv:
        S = one_pass(); out = {k: v for k, v in S.items() if k != "rate"}
        out["rate_now_pct_8h"] = S.get("rate", {}).get("now_pct_8h"); out["rate_7d"] = S.get("rate", {}).get("7d")
        print(json.dumps(out, indent=1))
        return
    log.info("fundlog started (hourly)")
    while True:
        try:
            one_pass()
        except Exception as e:
            log.error("pass: %s", e)
        now = time.time(); nxt = (int(now // 3600) + 1) * 3600 + 120
        time.sleep(max(60, nxt - now))


if __name__ == "__main__":
    main()
