r"""
collector.py -- snapshot(s) of live BTC option + BTCUSD perpetual quotes from Delta Exchange India.

Runs on GitHub Actions (see .github/workflows/), but works the same on any PC:
    python collector.py --out _out --tag halfhour                       # one snapshot
    python collector.py --out _out --tag evening --every 60 \
                        --from-ist 17:08 --until-ist 17:47              # one per minute in a window

Public endpoints only, NO API key, no account, no orders:
    GET /v2/tickers?contract_types=call_options,put_options&underlying_asset_symbols=BTC
    GET /v2/tickers/BTCUSD
    GET /v2/products (once per run -> settlement_time per symbol; falls back to the symbol's date)

Which contracts are kept (decided per snapshot, from the live chain itself):
    * expiries: current daily, next daily, current weekly, next weekly, current monthly
        - "daily"   = the two nearest expiries of any kind
        - "weekly"  = the two nearest Friday expiries
        - "monthly" = the nearest expiry that is the LAST Friday of its month
      (they overlap on some days -- a contract is stored once, with every tag that applies)
    * strikes from spot -25 % to spot +15 %
    * plus one BTCUSD perpetual row (opt_type = PERP)

Facts verified against the live API (2026-09-20 and 2026-10-02):
    * `timestamp` is an integer in MICROSECONDS, one value per snapshot. Numbers arrive as strings.
    * all BTC options settle 12:00 UTC (= 17:30 IST); expiry is in the symbol  C|P-BTC-<strike>-DDMMYY.
    * responses are CloudFront-cached (~10 s options, ~5 s perp) -> quote_age_s is stored.

Output (never invented, never filled):
    <out>/data/YYYY/MM/DD/quotes_<HHMM>_<tag>.csv.gz     one file per snapshot, UTC date and time
    <out>/data/YYYY/MM/DD/missing.csv                    one row per failed / skipped slot
The tag in the file name keeps the two workflows from ever writing the same file.
"""
import argparse
import csv
import gzip
import io
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://api.india.delta.exchange"
OPTIONS_PARAMS = {"contract_types": "call_options,put_options", "underlying_asset_symbols": "BTC"}

LOW_PCT, HIGH_PCT = -25.0, 15.0     # strike band around spot, in percent
MIN_OPTIONS_EXPECTED = 50           # fewer options than this in a reply = broken reply
SETTLEMENT_HOUR_UTC = 12

HTTP_TIMEOUT_S = 20
BACKOFF_S = (3, 8, 20)              # waits between the 4 attempts

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
SYMBOL_RE = re.compile(r"^([CP])-BTC-(\d+)-(\d{2})(\d{2})(\d{2})$")

COLUMNS = [
    "ts_utc", "ts_ist", "fetch_utc", "api_ts_utc", "quote_age_s", "tag",
    "symbol", "type", "strike", "expiry_utc", "minutes_to_expiry", "expiry_tags",
    "spot", "best_bid", "best_ask", "bid_size", "ask_size", "mark", "mark_iv", "bid_iv", "ask_iv",
    "delta", "gamma", "theta", "vega", "oi", "volume_24h",
    "funding_rate", "spread_pct_mark", "bid_at_floor", "ask_at_cap",
]
MISSING_COLUMNS = ["slot_utc", "slot_ist", "tag", "reason", "logged_utc"]


class CaptureError(RuntimeError):
    pass


def log(msg):
    print(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}Z  {msg}", flush=True)


def num(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def us_to_dt(v):
    """Epoch integer -> UTC datetime, unit detected from magnitude (s / ms / us / ns)."""
    v = int(v)
    div = 1e9 if v > 10**17 else 1e6 if v > 10**14 else 1e3 if v > 10**11 else 1
    return datetime.fromtimestamp(v / div, UTC)


def get_json(session, path, params=None):
    """GET with 4 attempts and growing back-off. Returns (payload, local UTC arrival time)."""
    last = None
    for attempt in range(len(BACKOFF_S) + 1):
        try:
            r = session.get(BASE + path, params=params, timeout=HTTP_TIMEOUT_S)
            got = datetime.now(UTC)
            if r.status_code != 200:
                raise CaptureError(f"HTTP {r.status_code}: {r.text[:200]!r}")
            data = r.json()
            if not data.get("success", False) or "result" not in data:
                raise CaptureError(f"success={data.get('success')!r}")
            return data, got
        except (requests.RequestException, ValueError, CaptureError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt < len(BACKOFF_S):
                time.sleep(BACKOFF_S[attempt])
    raise CaptureError(f"{path} failed after {len(BACKOFF_S) + 1} attempts ({last})")


def settlement_times(session):
    """symbol -> settlement datetime for live BTC options (one paginated /v2/products walk).
    Best-effort: on any failure returns {} and expiry falls back to the symbol's date at 12:00 UTC."""
    out, after = {}, None
    try:
        for _ in range(20):
            params = {"contract_types": "call_options,put_options", "states": "live", "page_size": 500}
            if after:
                params["after"] = after
            data, _ = get_json(session, "/v2/products", params)
            for p in data["result"]:
                sym, st = p.get("symbol", ""), p.get("settlement_time")
                if sym.startswith(("C-BTC-", "P-BTC-")) and st:
                    out[sym] = datetime.fromisoformat(st.replace("Z", "+00:00"))
            after = (data.get("meta") or {}).get("after")
            if not after:
                break
    except Exception as exc:                                         # noqa: BLE001
        log(f"products lookup failed, using symbol dates ({exc})")
        return {}
    return out


def is_last_friday(d):
    return d.weekday() == 4 and (d + timedelta(days=7)).month != d.month


def choose_expiries(expiries, now):
    """expiries: set of live expiry datetimes -> {expiry: 'daily1|weekly1|...'} for the ones we keep."""
    future = sorted(e for e in expiries if e > now)
    fridays = [e for e in future if e.weekday() == 4]
    monthly = [e for e in fridays if is_last_friday(e)]
    tags = {}
    for name, picks in (("daily", future[:2]), ("weekly", fridays[:2]), ("monthly", monthly[:1])):
        for i, e in enumerate(picks, 1):
            tags.setdefault(e, []).append(f"{name}{i}" if name != "monthly" else name)
    return {e: "|".join(t) for e, t in tags.items()}


def take_snapshot(session, settle, tag):
    """One snapshot -> list of row dicts. Raises CaptureError on a broken / incomplete reply."""
    perp_json, fetch_perp = get_json(session, "/v2/tickers/BTCUSD")
    opts_json, fetch_opt = get_json(session, "/v2/tickers", OPTIONS_PARAMS)

    perp = perp_json["result"]
    pq = perp.get("quotes") or {}
    p_bid, p_ask = num(pq.get("best_bid")), num(pq.get("best_ask"))
    if not (p_bid and p_ask and p_bid > 0 and p_ask > 0):
        raise CaptureError("perp has no two-sided quote")
    spot = num(perp.get("spot_price"))

    options = opts_json["result"]
    if not isinstance(options, list) or len(options) < MIN_OPTIONS_EXPECTED:
        raise CaptureError(f"only {len(options) if isinstance(options, list) else 'non-list'} options returned")
    if not spot:
        s = sorted(v for v in (num(o.get("spot_price")) for o in options) if v)
        spot = s[len(s) // 2]

    ts = fetch_opt.replace(second=0, microsecond=0)                 # the slot this snapshot belongs to
    parsed = []
    for o in options:
        m = SYMBOL_RE.match(o.get("symbol", ""))
        if not m:
            continue
        expiry = settle.get(o["symbol"]) or datetime(2000 + int(m.group(5)), int(m.group(4)), int(m.group(3)),
                                                     SETTLEMENT_HOUR_UTC, tzinfo=UTC)
        parsed.append((o, m, expiry))
    keep = choose_expiries({e for _, _, e in parsed}, fetch_opt)

    base = {"ts_utc": ts.isoformat(), "ts_ist": ts.astimezone(IST).isoformat(), "tag": tag}
    rows = []
    for o, m, expiry in parsed:
        strike = float(m.group(2))
        pct = (strike / spot - 1.0) * 100.0
        if expiry not in keep or not (LOW_PCT <= pct <= HIGH_PCT):
            continue
        q, g, band = o.get("quotes") or {}, o.get("greeks") or {}, o.get("price_band") or {}
        bid, ask, mark = num(q.get("best_bid")), num(q.get("best_ask")), num(o.get("mark_price"))
        bid = bid if bid and bid > 0 else None                       # empty side stays empty, never filled
        ask = ask if ask and ask > 0 else None
        lo, hi = num(band.get("lower_limit")), num(band.get("upper_limit"))
        api_ts = us_to_dt(o["timestamp"])
        rows.append({**base,
            "fetch_utc": fetch_opt.isoformat(), "api_ts_utc": api_ts.isoformat(),
            "quote_age_s": round((fetch_opt - api_ts).total_seconds(), 2),
            "symbol": o["symbol"], "type": m.group(1), "strike": strike,
            "expiry_utc": expiry.isoformat(), "minutes_to_expiry": round((expiry - fetch_opt).total_seconds() / 60, 1),
            "expiry_tags": keep[expiry], "spot": num(o.get("spot_price")) or spot,
            "best_bid": bid, "best_ask": ask, "bid_size": num(q.get("bid_size")), "ask_size": num(q.get("ask_size")),
            "mark": mark, "mark_iv": num(q.get("mark_iv")), "bid_iv": num(q.get("bid_iv")), "ask_iv": num(q.get("ask_iv")),
            "delta": num(g.get("delta")), "gamma": num(g.get("gamma")), "theta": num(g.get("theta")),
            "vega": num(g.get("vega")), "oi": num(o.get("oi_contracts")), "volume_24h": num(o.get("volume")),
            "funding_rate": None,
            "spread_pct_mark": round((ask - bid) / mark * 100, 4) if bid and ask and mark else None,
            "bid_at_floor": bool(bid and lo and bid <= lo + 1e-9),
            "ask_at_cap": bool(ask and hi and ask >= hi - 1e-9),
        })
    if not rows:
        raise CaptureError("no option survived the expiry/strike filter")

    p_ts = us_to_dt(perp["timestamp"])
    p_mark = num(perp.get("mark_price"))
    rows.append({**base,
        "fetch_utc": fetch_perp.isoformat(), "api_ts_utc": p_ts.isoformat(),
        "quote_age_s": round((fetch_perp - p_ts).total_seconds(), 2),
        "symbol": "BTCUSD", "type": "PERP", "strike": None, "expiry_utc": None, "minutes_to_expiry": None,
        "expiry_tags": None, "spot": spot, "best_bid": p_bid, "best_ask": p_ask,
        "bid_size": num(pq.get("bid_size")), "ask_size": num(pq.get("ask_size")), "mark": p_mark,
        "mark_iv": None, "bid_iv": None, "ask_iv": None, "delta": None, "gamma": None, "theta": None, "vega": None,
        "oi": num(perp.get("oi_contracts")), "volume_24h": num(perp.get("volume")),
        "funding_rate": num(perp.get("funding_rate")),
        "spread_pct_mark": round((p_ask - p_bid) / p_mark * 100, 5) if p_mark else None,
        "bid_at_floor": False, "ask_at_cap": False,
    })
    return ts, rows


def day_dir(out, ts):
    d = os.path.join(out, "data", f"{ts:%Y}", f"{ts:%m}", f"{ts:%d}")
    os.makedirs(d, exist_ok=True)
    return d


def write_snapshot(out, ts, tag, rows):
    """gzip CSV, written to .tmp then renamed -- a snapshot is complete or absent, never partial."""
    path = os.path.join(day_dir(out, ts), f"quotes_{ts:%H%M}_{tag}.csv.gz")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    with gzip.open(path + ".tmp", "wt", encoding="utf-8", compresslevel=9) as f:
        f.write(buf.getvalue())
    os.replace(path + ".tmp", path)
    return path


def record_missing(out, slot, tag, reason):
    path = os.path.join(day_dir(out, slot), "missing.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(MISSING_COLUMNS)
        w.writerow([slot.isoformat(), slot.astimezone(IST).isoformat(), tag, reason[:300],
                    datetime.now(UTC).replace(microsecond=0).isoformat()])


def one(session, settle, out, tag, slot):
    """One snapshot; on failure one missing.csv row. Returns True on success."""
    try:
        ts, rows = take_snapshot(session, settle, tag)
        path = write_snapshot(out, ts, tag, rows)
        n_opt = len(rows) - 1
        log(f"OK {ts:%Y-%m-%d %H:%M}Z ({ts.astimezone(IST):%H:%M} IST) options={n_opt} "
            f"spot={rows[-1]['spot']} -> {os.path.relpath(path, out)}")
        return True
    except Exception as exc:                                         # noqa: BLE001
        log(f"FAILED slot {slot:%H:%M}Z: {type(exc).__name__}: {exc}")
        record_missing(out, slot, tag, f"{type(exc).__name__}: {exc}")
        return False


def ist_today_at(hhmm, now):
    h, m = map(int, hhmm.split(":"))
    return now.astimezone(IST).replace(hour=h, minute=m, second=0, microsecond=0).astimezone(UTC)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=".", help="folder that receives data/ (default: current folder)")
    ap.add_argument("--tag", default="manual", help="label stored in every row and in the file name")
    ap.add_argument("--every", type=int, default=0, help="seconds between snapshots (0 = one snapshot)")
    ap.add_argument("--from-ist", help="window start HH:MM IST (loop mode)")
    ap.add_argument("--until-ist", help="window end HH:MM IST, inclusive (loop mode)")
    a = ap.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = "btc-option-quotes-collector (public market data, research)"
    settle = settlement_times(session)
    log(f"settlement times from /v2/products: {len(settle)} BTC options")

    now = datetime.now(UTC)
    if not a.every:
        slot = now.replace(second=0, microsecond=0)
        return 0 if one(session, settle, a.out, a.tag, slot) else 2

    # Loop mode: one snapshot at the start of every minute in [from, until] (IST). Every slot that
    # passes without a snapshot -- including ones already gone because the job started late -- is
    # written to missing.csv. Nothing is ever back-filled.
    start, end = ist_today_at(a.from_ist, now), ist_today_at(a.until_ist, now)
    step = timedelta(seconds=a.every)
    slot, ok, bad = start, 0, 0
    while slot <= end:
        now = datetime.now(UTC)
        if now >= slot + step:                                       # this slot is already past
            record_missing(a.out, slot, a.tag, "job not running at this time (GitHub start delay)")
            bad += 1
        else:
            if now < slot:
                time.sleep((slot - now).total_seconds() + 1)         # +1 s: land just after the minute
            if one(session, settle, a.out, a.tag, slot):
                ok += 1
            else:
                bad += 1
        slot += step
    log(f"window {a.from_ist}-{a.until_ist} IST done: {ok} snapshots, {bad} missing")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
