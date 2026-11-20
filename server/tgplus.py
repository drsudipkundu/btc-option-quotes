"""Extra Telegram commands for the night seller (20-Nov-2026, Sudip: "Build all").
/pnl /cum /tonight /guard /paper /server are read only. /ceiling changes the base ceiling only after /ceiling yes within 3 minutes.
Called from letterbox.telegram(); every function returns plain text."""
import os, sys, json, csv, time, math, shutil, subprocess, urllib.request, datetime as dt
HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
API = "https://api.india.delta.exchange"
VARIANTS = ("v5asl", "v5aslh", "v5aslf", "v5aslp", "v5aslk", "v5asl15", "v5aslhk", "v5aslj", "v5a", "v4asl", "v4a")


def _j(p, d=None):
    try:
        return json.load(open(os.path.join(HOME, p)))
    except Exception:
        return {} if d is None else d


def _get(path, q=None):
    u = API + path + (("?" + "&".join("%s=%s" % kv for kv in q.items())) if q else "")
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "tgplus"}), timeout=15))["result"]


def _tk(sym):
    t = _get("/v2/tickers/%s" % sym)
    qd = t.get("quotes") or {}
    f = lambda x: float(x) if x not in (None, "") else 0.0
    return f(qd.get("best_bid")), f(qd.get("best_ask")), f(t.get("mark_price")), f(t.get("spot_price"))


def pnl_text():
    S = _j("state/night_nlive.json")
    legs = S.get("legs", [])
    night = S.get("night")
    if not legs or not night:
        return "PNL: nothing sold yet tonight."
    out, unreal, spot = [], 0.0, 0.0
    for l in legs:
        if l.get("closed"):
            continue
        try:
            b, a, m, spot = _tk(l["sym"])
        except Exception:
            out.append("%s %s: price not available" % ("SOLD" if l["dir"] == "S" else "BOUGHT", l["sym"])); continue
        if l["dir"] == "S":
            u = (l["entry"] - (a or m)) * l["qty"]; out.append("SOLD %s %.3f @ %.1f, buy back now %.1f -> %+.2f USD" % (l["sym"], l["qty"], l["entry"], a or m, u))
        else:
            u = ((b or m) - l["entry"]) * l["qty"]; out.append("HEDGE %s %.3f @ %.1f, worth now %.1f -> %+.2f USD" % (l["sym"], l["qty"], l["entry"], b or m, u))
        unreal += u
    booked = sum(float(l.get("pnl") or 0) for l in legs if l.get("closed")) + sum(float(l.get("pnl_part") or 0) for l in legs if not l.get("closed"))
    return ("PNL night %s (BTC %.0f)\n%s\nOpen positions: %+.2f USD | already booked tonight: %+.2f USD | total so far %+.2f USD (about Rs %s)"
            % (night, spot, "\n".join(out) or "nothing open", unreal, booked, unreal + booked, format(int(round((unreal + booked) * 85, -1)), ",")))


def cum_text():
    rows = []
    try:
        for r in csv.reader(open(os.path.join(HOME, "logs", "trades_night_nlive.csv"))):
            if len(r) > 11 and r[3] == "NIGHT-END":
                rows.append((r[2], float(r[11] or 0)))
    except Exception:
        return "CUM: trade log not readable."
    if not rows:
        return "CUM: no finished night yet."
    now = dt.datetime.now(IST).date()
    d = lambda s: dt.date.fromisoformat(s)
    tot = sum(p for _, p in rows)
    wk = sum(p for n, p in rows if (now - d(n)).days < 7)
    mo = sum(p for n, p in rows if d(n).month == now.month and d(n).year == now.year)
    eq, peak, dd = 0.0, 0.0, 0.0
    for _, p in rows:
        eq += p; peak = max(peak, eq); dd = max(dd, peak - eq)
    best, worst = max(rows, key=lambda x: x[1]), min(rows, key=lambda x: x[1])
    losers = sum(1 for _, p in rows if p < 0)
    return ("CUMULATIVE (live, fees included)\nTotal %+.2f USD (about Rs %s) over %d nights, %d losing\nLast 7 days %+.2f | this month %+.2f\n"
            "Best %s %+.2f | worst %s %+.2f | biggest drop from a peak %.2f | now %.2f below the peak"
            % (tot, format(int(round(tot * 85, -1)), ","), len(rows), losers, wk, mo, best[0], best[1], worst[0], worst[1], dd, peak - eq))


def _rsi(cl, n=14):
    if len(cl) < n + 2:
        return None
    g = l = 0.0
    for i in range(1, n + 1):
        ch = cl[i] - cl[i - 1]; g += max(ch, 0); l += max(-ch, 0)
    g, l = g / n, l / n
    for i in range(n + 1, len(cl)):
        ch = cl[i] - cl[i - 1]; g = (g * (n - 1) + max(ch, 0)) / n; l = (l * (n - 1) + max(-ch, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def _pct(fname, p):
    vals, lo = [], (dt.date.today() - dt.timedelta(days=365)).isoformat()
    try:
        for r in csv.reader(open(os.path.join(HOME, "state", fname))):
            if r and r[0] >= lo:
                vals.append(float(r[1]))
    except Exception:
        return None, 0
    if len(vals) < 60:
        return None, len(vals)
    vals.sort()
    return vals[min(len(vals) - 1, int(p * len(vals)))], len(vals)


def tonight_text():
    c = _j("state/night_live_cfg.json")
    now = int(time.time())
    out = ["TONIGHT (preview, the bot decides at 23:30)",
           "Base: small %.2f BTC (first sale), big %s BTC (after every far option is bought within 1 h); flags mode %s"
           % (float(c.get("base", 0)), ("%.2f" % float(c["base_big"])) if c.get("base_big") else "set at 23:22", str(c.get("flagmode", "off")).upper())]
    try:
        d1 = _get("/v2/history/candles", {"resolution": "1d", "symbol": "BTCUSD", "start": now - 80 * 86400, "end": now})
        cl = [float(x["close"]) for x in sorted(d1, key=lambda x: x["time"])][:-1]
        sma = sum(cl[-50:]) / 50
        side = "PUT (BTC above its 50-day average)" if cl[-1] > sma else "CALL (BTC below its 50-day average)"
        out.append("Trend leg: %s; yesterday's close %.0f, 50-day average %.0f" % (side, cl[-1], sma))
        h4 = _get("/v2/history/candles", {"resolution": "4h", "symbol": "BTCUSD", "start": now - 40 * 86400, "end": now})
        r = _rsi([float(x["close"]) for x in sorted(h4, key=lambda x: x["time"])][:-1])
        if r is not None:
            on = (r >= 60) if cl[-1] > sma else (r < 40)
            out.append("4h RSI now %.1f -> RSI flag %s (put needs 60+, call needs under 40)" % (r, "ON" if on else "off"))
    except Exception as e:
        out.append("candles not available (%s)" % type(e).__name__)
    p90, n1 = _pct("prem_hist.csv", 0.90); v80, n2 = _pct("iv_hist.csv", 0.80)
    out.append("Premium flag needs >= %s %% of BTC (top 10 %%, %d nights); volatility flag needs >= %s (top 20 %%, %d nights)"
               % ("%.3f" % p90 if p90 else "?", n1, "%.3f" % v80 if v80 else "?", n2))
    try:
        e = dt.datetime.now(IST) + dt.timedelta(days=1)
        tk = _get("/v2/tickers", {"contract_types": "call_options,put_options", "underlying_asset_symbols": "BTC", "expiry_date": e.strftime("%d-%m-%Y")})
        spot = float(tk[0].get("spot_price") or 0)
        P = [float(t["strike_price"]) for t in tk if t.get("contract_type") == "put_options"]
        C = [float(t["strike_price"]) for t in tk if t.get("contract_type") == "call_options"]
        out.append("Listed for %s: puts down to %.0f (%.1f %% below BTC %.0f), calls up to %.0f (%.1f %% above). A far put needs about 6.5-8 %% below."
                   % (e.strftime("%d-%b"), min(P), (1 - min(P) / spot) * 100, spot, max(C), (max(C) / spot - 1) * 100))
    except Exception as ex:
        out.append("option list not available (%s)" % type(ex).__name__)
    return "\n".join(out)


def guard_text():
    S = _j("state/night_nlive.json")
    legs = [l for l in S.get("legs", []) if not l.get("closed")]
    if not legs:
        return "GUARD: nothing open."
    out = []
    for side in ("PE", "CE"):
        sold = [l for l in legs if l["dir"] == "S" and l["side"] == side and l.get("kind") != "ins"]
        if not sold:
            continue
        need = sum(l["qty"] for l in sold)
        cov = sum(l["qty"] for l in legs if l.get("kind") == "wing" and l["side"] == side and l["dir"] == "B")
        ins = any(l.get("kind") == "ins" and l["side"] == side for l in legs)
        g = (S.get("cg") or {}).get(side, {})
        k = max(l["strike"] for l in sold) if side == "PE" else min(l["strike"] for l in sold)
        atr_lvl = (g.get("ref", 0) - 2 * g.get("atr", 0)) if side == "PE" else (g.get("ref", 0) + 2 * g.get("atr", 0))
        if ins:
            st = "guard has FIRED (insurance bought)"
        elif cov >= need - 1e-9:
            st = "fully hedged (%.3f far options) - the far option protects" % cov
        else:
            lvl = max(atr_lvl, k) if side == "PE" else min(atr_lvl, k) if atr_lvl else k
            st = "NOT fully hedged (%.3f of %.3f) - guard fires if BTC reaches %.0f (sold strike %.0f)" % (cov, need, lvl, k)
        out.append("%s sold %.3f at strike %.0f: %s" % ("PUT" if side == "PE" else "CALL", need, k, st))
    return "GUARD\n" + "\n".join(out)


def paper_text():
    try:
        import nightlogic as NL
        lab = NL.LABELS
    except Exception:
        lab = {}
    rows = []
    for v in VARIANTS:
        S = _j("state/night_%s.json" % v)
        if not S:
            continue
        rows.append((float(S.get("total_pnl") or 0), "%s: %+.2f USD, %s nights%s" % (lab.get(v, v), float(S.get("total_pnl") or 0), S.get("nights", "?"),
                     " (open now)" if any(not l.get("closed") for l in S.get("legs", [])) else "")))
    live = _j("state/night_nlive.json")
    head = "PAPER COPIES (base 0.02 each; live: %+.2f USD over %s nights at its own base)" % (float(live.get("total_pnl") or 0), live.get("nights", "?"))
    return head + "\n" + "\n".join(t for _, t in sorted(rows, reverse=True))


def server_text():
    try:
        la = os.getloadavg()
    except Exception:
        la = (0, 0, 0)
    m = {}
    try:
        for ln in open("/proc/meminfo"):
            k, v = ln.split(":"); m[k] = int(v.split()[0]) * 1024
    except Exception:
        pass
    du = shutil.disk_usage(HOME)
    sv = []
    for s in ("nightlive", "nightbot", "shadowbot", "variantbot", "ladderlive", "ui"):
        try:
            sv.append("%s %s" % (s, subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True, timeout=3).stdout.strip()))
        except Exception:
            sv.append("%s ?" % s)
    try:
        bk = open(os.path.join(HOME, "logs", "backup.log")).read().strip().splitlines()[-1]
    except Exception:
        bk = "?"
    try:
        up = float(open("/proc/uptime").read().split()[0]) / 86400
    except Exception:
        up = 0
    mt, ma = m.get("MemTotal", 1), m.get("MemAvailable", 0)
    return ("SERVER\nLoad %.2f / %.2f / %.2f (%d cores) | memory used %.0f %% | disk used %.0f %% (%.1f GB free) | up %.1f days\n%s\nLast backup: %s"
            % (la[0], la[1], la[2], os.cpu_count() or 1, 100 * (1 - ma / mt), 100 * du.used / du.total, du.free / 1e9, up, " | ".join(sv), bk))


def ceiling_cmd(a, st):
    au = _j("state/autosize.json")
    cur = au.get("ceiling")
    if not a:
        return "CEILING now %s BTC. Change: /ceiling 0.25 (0.01 to 0.30), then /ceiling yes within 3 minutes." % (("%.2f" % cur) if cur else "not set")
    if a == ["yes"]:
        want = st.get("ceil_want")
        if want is None or time.time() - st.get("ceil_ask", 0) > 180:
            return "Nothing waiting. Send /ceiling 0.25 first."
        st["ceil_want"] = None
        py = os.path.join(HOME, "venv", "bin", "python")
        r = subprocess.run([py if os.path.exists(py) else sys.executable, "autosize.py", "--ceiling", "%.2f" % want], capture_output=True, text=True, timeout=60, cwd=HOME)
        return "CEILING CHANGED: %s\nIt applies at the next 23:22 check." % (r.stdout.strip() or r.stderr.strip())[-300:]
    try:
        want = float(a[0])
    except Exception:
        return "Send a number: /ceiling 0.25"
    if not (0.01 <= want <= 0.30):
        return "REFUSED: the ceiling must be 0.01 to 0.30 BTC."
    st["ceil_want"], st["ceil_ask"] = want, time.time()
    return "CEILING asks: change %s -> %.2f BTC? Send /ceiling yes within 3 minutes. Anything else = no change." % (("%.2f" % cur) if cur else "not set", want)
