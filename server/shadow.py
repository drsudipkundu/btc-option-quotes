"""Shadow fleet (29-Oct-2026): parameter-health monitor for the night option sell.

Runs ~20 PAPER copies of v4A-CG-SL side by side on the same live Delta India quotes. Each copy changes ONE
parameter (slope threshold, strike distance, moved-night switch, crash guard, buy-back, $ floor, IV boost,
quiet-day guard). Every finished night is written to logs/shadow_nights.csv. The page (/health on the control
page) compares every copy with the base copy night by night (paired difference + t-score) and checks the base
against the 6.7-year backtest rates. A parameter whose neighbour keeps winning for 20+ nights without a worse
worst-night is flagged "RESET CANDIDATE". Nothing here places orders or changes the real strategies.
Run: python shadow.py (service shadowbot) | python shadow.py --check (one look now, no state change)
"""
import os, sys, json, csv, math, time, logging, datetime as dt
from logging.handlers import RotatingFileHandler

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
import nightlogic as NL
from nightlogic import Night, parse_chain, next_expiry_ts, indicators, find, fee, is_full, IST, UTC, DAILY

SDIR = os.path.join(HOME, "state", "shadow")
LDIR = os.path.join(HOME, "logs", "shadow")
NIGHTS_CSV = os.path.join(HOME, "logs", "shadow_nights.csv")
NCOLS = ["night", "id", "pnl_usd", "legs", "traded", "half", "sl_acc", "side", "moved", "cg", "why"]
log = logging.getLogger("shadow")

# Base = v4A-CG-SL exactly as live/paper today. Each shadow overrides one value.
BASE = dict(rule="v4a", dist_n=0.025, k=1.4, moved_hv=NL.MOVED_HV, main_mv=0.005, rg=1.0, decay=0.10, cg=2.0,
            ins=0.04, min_bid=NL.MIN_BID, iv_k=1.40, sl_thr=0.123, sl_cut=0.5)
FLEET = [
    ("base", "BASE = v4A-CG-SL today", {}),
    ("sl_off", "slope rule OFF (= v4A-CG)", dict(sl_thr=None)),
    ("sl_000", "slope threshold 0.00", dict(sl_thr=0.0)),
    ("sl_250", "slope threshold 0.25", dict(sl_thr=0.25)),
    ("dist_20", "normal distance 2.0%", dict(dist_n=0.020)),
    ("dist_30", "normal distance 3.0%", dict(dist_n=0.030)),
    ("k_12", "moved distance 1.2 sigma", dict(k=1.2)),
    ("k_16", "moved distance 1.6 sigma", dict(k=1.6)),
    ("mhv_25", "moved switch HV14 > 0.25", dict(moved_hv=0.25)),
    ("mhv_32", "moved switch HV14 > 0.32", dict(moved_hv=0.32)),
    ("rg_07", "quiet-day guard 0.7", dict(rg=0.7)),
    ("rg_13", "quiet-day guard 1.3", dict(rg=1.3)),
    ("cg_15", "crash guard 1.5 x ATR", dict(cg=1.5)),
    ("cg_25", "crash guard 2.5 x ATR", dict(cg=2.5)),
    ("cg_off", "crash guard OFF", dict(cg=None)),
    ("dec_80", "buy back at 80% decay", dict(decay=0.20)),
    ("dec_off", "no early buy-back", dict(decay=None)),
    ("bid_05", "floor bid $5", dict(min_bid=5.0)),
    ("bid_15", "floor bid $15", dict(min_bid=15.0)),
    ("boost_off", "IV boost OFF", dict(iv_k=None)),
]
GROUPS = {"sl": "Slope threshold (0.123)", "dist": "Normal distance (2.5%)", "k": "Moved distance (1.4 sigma)",
          "mhv": "Moved switch (HV14 0.283)", "rg": "Quiet-day guard (1.0)", "cg": "Crash guard (2 x ATR)",
          "dec": "Early buy-back (90%)", "bid": "Bid floor ($10)", "boost": "IV boost (1.4)"}
# 6.7-year Deribit backtest of v4A-CG (claude/v4cg-v5cg-fresh-backtest-slope-half-2026-10-29.md), test period after Apr-2024
REF = dict(trade_rate=0.658, win_rate=0.981, flag_rate=0.164, moved_rate=0.711)
ACC_Q = [(-0.228, 5), (-0.094, 25), (-0.002, 50), (0.084, 75), (0.121, 83), (0.222, 95)]

class Shadow(Night):
    def __init__(self, sid, label, over, base_qty):
        self.sid, self.label = sid, label
        self.P = dict(BASE, **over)
        Night.__init__(self, "v4asl", base_qty, HOME)
        self.lab = "SHADOW " + sid
        self.state_path = os.path.join(SDIR, "%s.json" % sid)
        self.csv_path = os.path.join(LDIR, "trades_%s.csv" % sid)
        self.S = dict(night=None, exp=0, legs=[], fired=[], picks={}, cg={"PE": {}, "CE": {}}, next_id=1,
                      total_pnl=0.0, nights=0, window_closed=None)
        self.load()
        self.notify = lambda s, b="": None

    # ---- sizing / rules with this copy's parameters
    def size_base(self, ind):
        t = self.P["sl_thr"]
        if t is not None and ind.get("sl_acc") is not None and ind["sl_acc"] > t:
            return round(self.base * self.P["sl_cut"], 3)
        return self.base

    def is_moved(self, ind):
        return ind["hv14"] > self.P["moved_hv"]

    def plan(self, ind):
        P, base = self.P, self.size_base(ind)
        main = abs(ind["c1"] / ind["c2"] - 1) >= P["main_mv"]
        quiet = (not main) and (ind["h1"] - ind["l1"]) / ind["c2"] >= P["rg"] * ind["hv14"] * DAILY
        if not (main or quiet):
            return []
        side = "PE" if ind["c1"] > ind["sma50"] else "CE"
        moved = self.is_moved(ind)
        q = base * (2 if moved else 1) if main else base
        return [dict(key="trend", side=side, kind="main" if main else "quiet", qty=q, pk="m" if moved else "n")]

    def boost_qty(self, ind):
        if self.P["iv_k"] is None or abs(ind["c1"] / ind["c2"] - 1) < self.P["main_mv"]:
            return 0
        return self.size_base(ind) * (1 if self.is_moved(ind) else 0.5)

    def picks(self, spot, hv14, ch):
        P = self.P
        mv = hv14 * NL.K_SIG * P["k"] / 1.4
        full = self.S.get("full", [])
        pe = sorted(o["strike"] for o in ch if o["typ"] == "PE" and not is_full(o, full))
        ce = sorted(o["strike"] for o in ch if o["typ"] == "CE" and not is_full(o, full))

        def put(t):
            return max([k for k in pe if k <= t], default=0)

        def call(t):
            return min([k for k in ce if k >= t], default=9999999)
        return {"pe_n": put(spot * (1 - P["dist_n"])), "pe_m": put(spot * (1 - mv)),
                "ce_n": call(spot * (1 + P["dist_n"])), "ce_m": call(spot * (1 + mv)), "jumps": {}}

    # ---- main tick (same flow as Night.step, parameterised)
    def step(self, now, spot, ch, ind, stopped=False):
        hm = now.hour * 100 + now.minute
        today = now.strftime("%Y-%m-%d")
        if self.open_legs() and now.timestamp() > self.S["exp"] + 600:
            self._settle(now, spot)
            return True
        if self.open_legs() and self.S["night"] and today > self.S["night"] and hm >= 1720:
            self._universal_exit(now, spot, ch)
            return True
        if self.open_legs() and self.S["exp"]:
            ch = [o for o in ch if o["exp"] == self.S["exp"]]
        if not ch:
            return False
        changed = False
        dec = self.P["decay"]
        if hm < 2330 and dec is not None:
            for l in self.open_legs():
                if l["dir"] == "S":
                    o = find(ch, l["side"], l["strike"])
                    if o and o["mark"] > 0 and o["mark"] <= dec * l["entry"]:
                        self._close(now, spot, l, o, "DECAY")
                        changed = True
        if 2330 <= hm <= 2358 and ind and not stopped:
            changed |= self._entries(now, spot, ch, ind, today)
        if (hm >= 2330 or hm < 1715) and self.open_legs() and ind and self.P["cg"] is not None:
            changed |= self._crash_guard(now, spot, ch, ind)
        if changed:
            self.save()
        return changed

    def _entries(self, now, spot, ch, ind, today):
        S, P = self.S, self.P
        if S["night"] != today:
            if self.open_legs():
                return False
            S.update(night=today, fired=[], picks={}, cg={"PE": {}, "CE": {}}, full=[], meta={})
            S["exp"] = min([o["exp"] for o in ch if o["exp"] > now.timestamp()], default=0)
            S["meta"] = dict(half=int(self.size_base(ind) < self.base), sl_acc=ind.get("sl_acc"),
                             moved=int(self.is_moved(ind)), side="PE" if ind["c1"] > ind["sma50"] else "CE")
        if S["exp"]:
            ch = [o for o in ch if o["exp"] == S["exp"]]
        if ind["hv14"] is None or ind["hv7"] is None:
            return False
        pk = self.picks(spot, ind["hv14"], ch)
        S["picks"] = pk
        changed = False
        for p in self.plan(ind):
            if p["key"] in S["fired"]:
                continue
            strike = pk["%s_%s" % (p["side"].lower(), p["pk"])]
            if strike in (0, 9999999):
                continue
            o = find(ch, p["side"], strike)
            if not o or o["bid"] < P["min_bid"] or self.net_short(p["side"]) > 1e-9:
                continue
            if self._open(now, spot, p["key"], p["kind"], p["side"], o, round(p["qty"], 3), "S"):
                S["fired"].append(p["key"])
                changed = True
        bq = self.boost_qty(ind)
        if bq and "boost" not in S["fired"]:
            t = [l for l in self.open_legs() if l["set"] == "trend" and l["kind"] == "main" and l["dir"] == "S"]
            if t:
                m = t[0]
                o = find(ch, m["side"], m["strike"])
                if o and o["iv"] * 100 >= P["iv_k"] * 100 * ind["hv7"] and abs(self.net_short(m["side"])) < 1.2 * m["qty"]:
                    if self._open(now, spot, "boost", "boost", m["side"], o, round(bq, 3), "S"):
                        S["fired"].append("boost")
                        changed = True
        return changed

    def _crash_guard(self, now, spot, ch, ind):
        S, P, changed = self.S, self.P, False
        ch = [o for o in ch if o["exp"] == S["exp"]] if S["exp"] else ch
        for side in ("PE", "CE"):
            g = S["cg"][side]
            net = self.net_short(side)
            if not (net > 0.0005) or g.get("st") == 2:
                continue
            if not g.get("ref"):
                g.update(ref=spot, atr=ind["atr"], st=1)
                changed = True
                continue
            lvl = g["ref"] - P["cg"] * g["atr"] if side == "PE" else g["ref"] + P["cg"] * g["atr"]
            if not (g["atr"] and (spot <= lvl if side == "PE" else spot >= lvl)):
                continue
            strikes = sorted(o["strike"] for o in ch if o["typ"] == side and not is_full(o, S.get("full", [])))
            if not strikes:
                continue
            pk = S["picks"] or {}
            if side == "PE":
                tgt = min(lvl * (1 - P["ins"]), pk.get("pe_n") or lvl, pk.get("pe_m") or lvl)
                best = max([k for k in strikes if k <= tgt], default=0) or strikes[0]
            else:
                cap = max(pk.get("ce_n") or 0, pk.get("ce_m") or 0)
                tgt = max(lvl * (1 + P["ins"]), 0 if cap > 9000000 else cap)
                best = min([k for k in strikes if k >= tgt], default=0) or strikes[-1]
            o = find(ch, side, best)
            if o and self._open(now, spot, "crashguard", "ins", side, o, round(net, 3), "B", "trigger %.1f" % lvl):
                g.update(st=2, lvl=lvl, strike=best)
                changed = True
        return changed

    def _finish(self, now, why):
        legs = [l for l in self.S["legs"] if l.get("pnl") is not None]
        pnl = sum(l["pnl"] for l in legs)
        m = self.S.get("meta") or {}
        new = not os.path.exists(NIGHTS_CSV)
        with open(NIGHTS_CSV, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(NCOLS)
            w.writerow([self.S["night"], self.sid, round(pnl, 4), len(legs), int(any(l["dir"] == "S" for l in legs)),
                        m.get("half", ""), "" if m.get("sl_acc") is None else round(m["sl_acc"], 4), m.get("side", ""),
                        m.get("moved", ""), int(any(l["set"] == "crashguard" for l in legs)), why])
        self.S["nights"] += 1
        self.S["recorded"] = self.S["night"]
        self.S["last_night"] = dict(night=self.S["night"], pnl=pnl, legs=len(legs))
        self.S["legs"] = []
        self.save()

    def close_night_if_idle(self, now):
        """A night that sold nothing (or whose legs all closed early) still counts: record it after 17:20 next day."""
        S = self.S
        if not S.get("night") or self.open_legs() or S.get("recorded") == S["night"]:
            return False
        if now.strftime("%Y-%m-%d") > S["night"] and now.hour * 100 + now.minute >= 1720:
            S["recorded"] = S["night"]
            self._finish(now, "no trade" if not S["legs"] else "closed early")
            return True
        return False

# ---------------------------------------------------------------- runner
class Feed:
    def __init__(self):
        import delta_api as d
        self.d = d

    def spot(self):
        return float(self.d.public("/v2/tickers/BTCUSD")["result"]["mark_price"])

    def candles(self, now):
        r = self.d.public("/v2/history/candles", {"resolution": "1d", "symbol": "BTCUSD",
                                                  "start": int(now - 400 * 86400), "end": int(now)})["result"]
        return sorted(r, key=lambda x: x["time"])

    def chain(self, exp_ts):
        date = dt.datetime.fromtimestamp(exp_ts, UTC).strftime("%d-%m-%Y")
        base = {"contract_types": "call_options,put_options", "underlying_asset_symbols": "BTC"}
        ch = []
        try:
            ch = parse_chain(self.d.public("/v2/tickers", dict(base, expiry_date=date))["result"])
        except Exception as e:
            log.warning("filtered chain failed: %s", e)
        ch = [o for o in ch if o["exp"] == exp_ts]
        if not ch:
            ch = [o for o in parse_chain(self.d.public("/v2/tickers", base)["result"]) if o["exp"] == exp_ts]
        return ch

def make_fleet(base_qty):
    os.makedirs(SDIR, exist_ok=True)
    os.makedirs(LDIR, exist_ok=True)
    return [Shadow(i, l, o, base_qty) for i, l, o in FLEET]

def tick(fleet, feed, cache, now_ts):
    now = dt.datetime.fromtimestamp(now_ts, IST)
    hm = now.hour * 100 + now.minute
    for s in fleet:
        if s.close_night_if_idle(now):
            s.save()
    in_window = 2325 <= hm <= 2358
    open_any = any(s.open_legs() for s in fleet)
    if not (in_window or open_any):
        return 60
    if not cache.get("ind") or now_ts - cache.get("t", 0) >= (60 if in_window else 900):
        cache["ind"], cache["t"] = indicators(feed.candles(now_ts), now_ts), now_ts
    ind = cache["ind"]
    spot = feed.spot()
    exp_ts = next((s.S["exp"] for s in fleet if s.open_legs() and s.S["exp"]), 0) or next_expiry_ts(now_ts)
    ch = feed.chain(exp_ts)
    for s in fleet:
        try:
            s.step(now, spot, ch, ind)
        except Exception as e:
            log.exception("shadow %s step failed: %s", s.sid, e)
    return 10 if in_window else 30

def run():
    os.makedirs(os.path.join(HOME, "logs"), exist_ok=True)
    log.setLevel(logging.INFO)
    h = RotatingFileHandler(os.path.join(HOME, "logs", "shadow.log"), maxBytes=1_000_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HOME, ".env"))
    fleet = make_fleet(float(os.getenv("NIGHT_BASE", "0.02")))
    feed, cache, fails, beat = Feed(), {}, 0, 0
    log.info("shadow fleet started: %d paper copies", len(fleet))
    while True:
        try:
            wait = tick(fleet, feed, cache, time.time())
            fails = 0
        except Exception as e:
            fails += 1
            log.exception("tick failed (%d): %s", fails, e)
            wait = min(120, 10 * fails)
        if time.time() - beat > 1800:
            beat = time.time()
            log.info("beat | " + " ".join("%s:%d/%.2f" % (s.sid, len(s.open_legs()), s.S["total_pnl"]) for s in fleet))
        time.sleep(wait)

# ---------------------------------------------------------------- health analysis + page
def read_nights():
    out = {}
    try:
        for r in csv.DictReader(open(NIGHTS_CSV)):
            out.setdefault(r["id"], {})[r["night"]] = r
    except Exception:
        pass
    return out

def pct_of(acc):
    if acc is None:
        return "-"
    p = 0
    for v, q in ACC_Q:
        if acc >= v:
            p = q
    return "above %d%% of past days" % p if p else "below 5% of past days"

def compare(nights, sid, window=60):
    b, v = nights.get("base", {}), nights.get(sid, {})
    common = sorted(set(b) & set(v))[-window:]
    d = [float(v[n]["pnl_usd"]) - float(b[n]["pnl_usd"]) for n in common]
    n = len(d)
    tot_v = sum(float(v[k]["pnl_usd"]) for k in common)
    worst_v = min([float(v[k]["pnl_usd"]) for k in common], default=0.0)
    worst_b = min([float(b[k]["pnl_usd"]) for k in common], default=0.0)
    if n >= 2:
        m = sum(d) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
        t = m / (sd / math.sqrt(n)) if sd > 1e-9 else (0.0 if abs(m) < 1e-9 else math.copysign(9.9, m))
    else:
        m, t = 0.0, 0.0
    if n < 15:
        st = "collecting"
    elif n >= 20 and t >= 2.0 and worst_v >= worst_b - 1e-9:
        st = "RESET CANDIDATE"
    elif t >= 1.5:
        st = "better - watch"
    elif t <= -1.5:
        st = "worse"
    else:
        st = "same"
    return dict(n=n, total=tot_v, diff=sum(d), t=t, worst=worst_v, status=st)

def base_health(nights, window=60):
    b = nights.get("base", {})
    rows = [b[k] for k in sorted(b)[-window:]]
    n = len(rows)
    out = []
    if not n:
        return out
    traded = [r for r in rows if r["traded"] == "1"]

    def chk(name, k, total, ref):
        if total == 0:
            return out.append((name, "-", "%.0f%%" % (100 * ref), "no data"))
        p = k / total
        z = (p - ref) / math.sqrt(ref * (1 - ref) / total) if 0 < ref < 1 else 0
        st = "collecting" if total < 20 else ("DRIFT" if abs(z) >= 2.5 else ("watch" if abs(z) >= 2 else "ok"))
        out.append((name, "%.0f%% (%d/%d)" % (100 * p, k, total), "%.0f%%" % (100 * ref), st))
    chk("Nights that traded", len(traded), n, REF["trade_rate"])
    chk("Winning nights (of traded)", sum(1 for r in traded if float(r["pnl_usd"]) > 0), len(traded), REF["win_rate"])
    chk("Slope rule halved size", sum(1 for r in rows if r["half"] == "1"), n, REF["flag_rate"])
    chk("Moved nights (HV14 high)", sum(1 for r in rows if r["moved"] == "1"), n, REF["moved_rate"])
    return out

def page_html():
    E = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    nights = read_nights()
    acc = None
    try:
        st = json.load(open(os.path.join(SDIR, "base.json")))
        acc = (st.get("meta") or {}).get("sl_acc")
    except Exception:
        st = {}
    fleet = {i: (l, o) for i, l, o in FLEET}
    h = ['<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         '<meta http-equiv="refresh" content="60"><title>Parameter health</title><style>'
         '*{box-sizing:border-box}body{font-family:system-ui,sans-serif;margin:0;background:#f4f5f7;color:#1c2430}'
         '.w{max-width:900px;margin:0 auto;padding:12px 14px 40px}h1{font-size:20px;margin:6px 0}.m{color:#6b7684;font-size:12px}'
         '.row{background:#fff;border-radius:12px;padding:14px;margin:12px 0;box-shadow:0 1px 3px #0001;overflow-x:auto}'
         'table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:5px 4px;text-align:left;border-bottom:1px solid #e5e8ec;white-space:nowrap}'
         '.b{display:inline-block;border-radius:6px;padding:1px 7px;font-size:12px;font-weight:700}'
         '.ok{background:#dcfce7;color:#166534}.wa{background:#fef3c7;color:#92400e}.bad{background:#fee2e2;color:#991b1b}.gr{background:#e5e8ec;color:#374151}'
         'a{color:#0369a1}</style></head><body><div class="w">'
         '<p><a href="/">&larr; My Bots</a></p><h1>Parameter health (shadow fleet)</h1>'
         '<p class="m">' + str(len(FLEET)) + ' paper copies of v4A-CG-SL trade the same live Delta quotes every night, each with ONE value changed. '
         'Paper only, never real orders. Results build up night by night: a verdict needs 15-20 finished nights.</p>']

    def badge(s):
        c = {"ok": "ok", "same": "ok", "collecting": "gr", "watch": "wa", "better - watch": "wa", "worse": "gr",
             "DRIFT": "bad", "RESET CANDIDATE": "bad"}.get(s, "gr")
        return '<span class="b %s">%s</span>' % (c, E(s))
    h.append('<div class="row"><b>Slope rule today</b><br>Speed-up reading (last completed day): <b>%s</b> &mdash; %s. '
             'Half size when above 0.123.</div>' % ("-" if acc is None else "%.3f" % acc, pct_of(acc)))
    h.append('<div class="row"><b>Is the base strategy behaving like its backtest?</b> (last 60 nights vs 6.7-year test)'
             '<table><tr><th>Check</th><th>Now</th><th>Backtest</th><th>Status</th></tr>')
    bh = base_health(nights)
    for name, now_, ref, s in bh:
        h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (E(name), now_, ref, badge(s)))
    if not bh:
        h.append('<tr><td colspan="4" class="m">No finished night yet. The first one is recorded after 17:20 IST tomorrow.</td></tr>')
    h.append("</table></div>")
    h.append('<div class="row"><b>Each parameter: does a neighbour value do better?</b> (same nights, last 60)'
             '<table><tr><th>Copy</th><th>Nights</th><th>Total $</th><th>vs base $</th><th>t-score</th><th>Worst night $</th><th>Verdict</th></tr>')
    last = None
    for sid, (lab, over) in fleet.items():
        g = sid.split("_")[0]
        if g != last and g in GROUPS:
            h.append('<tr><td colspan="7" style="background:#f8fafc"><b>%s</b></td></tr>' % E(GROUPS[g]))
        last = g
        c = compare(nights, sid) if sid != "base" else dict(n=len(nights.get("base", {})), total=sum(float(r["pnl_usd"]) for r in nights.get("base", {}).values()), diff=0, t=0, worst=min([float(r["pnl_usd"]) for r in nights.get("base", {}).values()], default=0), status="base")
        h.append("<tr><td>%s</td><td>%d</td><td>%.2f</td><td>%s</td><td>%s</td><td>%.2f</td><td>%s</td></tr>" % (
            E(lab), c["n"], c["total"], "" if sid == "base" else "%+.2f" % c["diff"], "" if sid == "base" else "%.1f" % c["t"],
            c["worst"], "" if sid == "base" else badge(c["status"])))
    h.append("</table><p class='m'>t-score = how consistently the copy beat the base night by night (paired). "
             "RESET CANDIDATE = 20+ nights, t-score 2 or more, and a worst night no worse than the base. "
             "It is a prompt to re-test that value on the long backtest, not an automatic change.</p></div>")
    open_n = 0
    try:
        for i, _, _ in FLEET:
            s = json.load(open(os.path.join(SDIR, "%s.json" % i)))
            open_n += len([l for l in s.get("legs", []) if not l.get("closed")])
    except Exception:
        pass
    h.append('<p class="m">Open shadow legs now: %d. Files: logs/shadow_nights.csv, logs/shadow/trades_*.csv. '
             'Fees included, funding not modelled.</p></div></body></html>' % open_n)
    return "".join(h).encode()

def check():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HOME, ".env"))
    feed = Feed()
    now = time.time()
    ind = indicators(feed.candles(now), now)
    spot = feed.spot()
    ch = feed.chain(next_expiry_ts(now))
    print("spot %.1f | slope accel %.3f | listed options %d" % (spot, ind["sl_acc"], len(ch)))
    for s in make_fleet(float(os.getenv("NIGHT_BASE", "0.02"))):
        pk = s.picks(spot, ind["hv14"], ch)
        pl = s.plan(ind)
        txt = []
        for p in pl:
            k = pk["%s_%s" % (p["side"].lower(), p["pk"])]
            o = find(ch, p["side"], k) if k not in (0, 9999999) else None
            txt.append("%s %s %s x %.3f bid %s" % (p["kind"], p["side"], k, p["qty"], o["bid"] if o else "-"))
        print("%-10s %-28s %s" % (s.sid, s.label, "; ".join(txt) or "no trade"))

if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        run()
