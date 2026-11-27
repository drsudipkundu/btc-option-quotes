#!/usr/bin/env python3
"""addpaper - PAPER LOGGER for "add after an adverse move, always hedged" (c32, 27-Nov-2026, Sudip 15:53 "build it").
Public Delta data only (GET): no API key, never places an order, never touches any bot. It answers the one thing the model could not:
what price does the ADD really get after the move, and what do the two hedge choices really cost?

Every night (run by cron every 2 minutes):
  23:30 IST  ANCHOR: spot x; per side the strike to watch K and its hedge strike Kh. If the live seller holds sold options for tonight, ITS strikes and far
             options are used (src=live, read-only from state/night_nlive.json); otherwise the nearest listed strike 2.5 % out and the far option 4 % beyond (src=model).
  until 05:30 IST  TRIGGER: the first time BTC is 1.0 % and the first time it is 1.5 % against a side (up for the call, down for the put), it records real quotes:
             bid of the SAME strike K, bid of a NEW strike Kn (nearest 2.5 % from the new price), ask of the OLD hedge Kh, ask of a NEW hedge Khn (nearest 4 % beyond Kn).
  after 17:30 IST  SETTLE: S = average of the last 30 one-minute closes before expiry. Paper result per 1 BTC of each variant = bid of the add - ask of its hedge
             - payout of the add + payout of the hedge:  A1 same strike + old hedge, A2 same strike + new hedge, B1 new strike + old hedge, B2 new strike + new hedge.
Files: ~/deltabot/addpaper/state.json, triggers.csv, outcomes.csv.   Usage: addpaper.py [run] | report"""
import csv, datetime as dt, json, os, socket, sys, time, urllib.request, urllib.parse

_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

API = "https://api.india.delta.exchange"
HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
OUT = os.path.join(HOME, "addpaper")
STF, TRG, OUTC = os.path.join(OUT, "state.json"), os.path.join(OUT, "triggers.csv"), os.path.join(OUT, "outcomes.csv")
DIST, WING, THR, WINDOW_H = 0.025, 0.04, (1.0, 1.5), 6.0
TF = ["exp_ts", "side", "thr", "src", "t_ts", "mins", "x", "s", "K", "Kh", "Kn", "Khn", "bid_same", "mark_same", "bid_new", "mark_new", "ask_old", "mark_old", "ask_newh", "mark_newh"]
OF = TF + ["S", "A1", "A2", "B1", "B2"]


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "addpaper/1"})
    return json.load(urllib.request.urlopen(req, timeout=15))["result"]


def num(v):
    try:
        return float(v)
    except Exception:
        return None


def next_expiry(now):
    e = (int(now) // 86400) * 86400 + 12 * 3600
    return e if e > now else e + 86400


def chain(exp_ts, G=get):
    """{('C'|'P', strike): dict(sym, bid, ask, mark)} for that expiry"""
    tick = G("/v2/tickers", {"contract_types": "call_options,put_options", "underlying_asset_symbols": "BTC",
                             "expiry_date": dt.datetime.fromtimestamp(exp_ts, dt.timezone.utc).strftime("%d-%m-%Y")})
    out = {}
    for t in tick:
        p = str(t.get("symbol", "")).split("-")
        if len(p) != 4 or p[0] not in ("C", "P"):
            continue
        q = t.get("quotes") or {}
        out[(p[0], float(p[2]))] = dict(sym=t["symbol"], bid=num(q.get("best_bid")), ask=num(q.get("best_ask")), mark=num(t.get("mark_price")))
    return out


def nearest(ch, side, target):
    ks = [k for (s, k) in ch if s == side]
    return min(ks, key=lambda k: abs(k - target)) if ks else None


def sgn(side):
    return 1 if side == "C" else -1


def live_strikes(exp_ts):
    """sold strike and far option strike per side from the live seller's own state file (read only); {} if none for this expiry"""
    try:
        st = json.load(open(os.path.join(HOME, "state", "night_nlive.json")))
    except Exception:
        return {}
    tag = dt.datetime.fromtimestamp(exp_ts, dt.timezone.utc).strftime("%d%m%y")
    out = {}
    for l in st.get("legs") or []:
        sym = str(l.get("sym", ""))
        if l.get("closed") or not sym.endswith(tag) or l.get("kind") == "ins":
            continue
        side = "C" if l.get("side") == "CE" else "P"
        d = out.setdefault(side, {})
        if l.get("dir") == "S":
            d["K"] = float(l["strike"])
        elif l.get("kind") == "wing":
            d["Kh"] = float(l["strike"])
    return {s: d for s, d in out.items() if "K" in d}


def anchor(now, G=get, live=live_strikes):
    exp = next_expiry(now)
    a0 = exp - 18 * 3600                                  # 23:30 IST = 18:00 UTC the day before
    if not a0 <= now <= a0 + 900:
        return None
    x = float(G("/v2/tickers/BTCUSD")["mark_price"])
    ch = chain(exp, G); lv = live(exp) or {}
    sides = {}
    for side in ("C", "P"):
        if side in lv:
            K = lv[side]["K"]; Kh = lv[side].get("Kh") or nearest(ch, side, K * (1 + sgn(side) * WING)); src = "live"
        else:
            K = nearest(ch, side, x * (1 + sgn(side) * DIST)); Kh = nearest(ch, side, (K or x) * (1 + sgn(side) * WING)); src = "model"
        if K is None or Kh is None:
            continue
        sides[side] = dict(K=K, Kh=Kh, src=src, done=[])
    return dict(exp=exp, t0=int(now), x=x, sides=sides, settled=False)


def check(st, now, G=get):
    """returns trigger rows recorded now"""
    rows = []
    if not st or now >= st["exp"] or now - st["t0"] > WINDOW_H * 3600:
        return rows
    s = float(G("/v2/tickers/BTCUSD")["mark_price"]); ch = None
    for side, d in st["sides"].items():
        adv = sgn(side) * (s / st["x"] - 1) * 100
        for thr in THR:
            if thr in d["done"] or adv < thr:
                continue
            ch = ch or chain(st["exp"], G)
            Kn = nearest(ch, side, s * (1 + sgn(side) * DIST)); Khn = nearest(ch, side, Kn * (1 + sgn(side) * WING))
            q = lambda k: ch.get((side, k), {})
            rows.append(dict(exp_ts=st["exp"], side=side, thr=thr, src=d["src"], t_ts=int(now), mins=round((now - st["t0"]) / 60), x=st["x"], s=s,
                             K=d["K"], Kh=d["Kh"], Kn=Kn, Khn=Khn,
                             bid_same=q(d["K"]).get("bid"), mark_same=q(d["K"]).get("mark"), bid_new=q(Kn).get("bid"), mark_new=q(Kn).get("mark"),
                             ask_old=q(d["Kh"]).get("ask"), mark_old=q(d["Kh"]).get("mark"), ask_newh=q(Khn).get("ask"), mark_newh=q(Khn).get("mark")))
            d["done"].append(thr)
    return rows


def pay(side, K, S):
    return max(S - K, 0.0) if side == "C" else max(K - S, 0.0)


def variant(side, bid, K, ask, Kh, S):
    """paper result per 1 BTC, or '' when a quote is missing or the hedge is not beyond the strike"""
    if bid in (None, "") or ask in (None, "") or K in (None, "") or Kh in (None, ""):
        return ""
    bid, ask, K, Kh = float(bid), float(ask), float(K), float(Kh)
    if sgn(side) * (Kh - K) <= 0:
        return ""
    return round(bid - ask - pay(side, K, S) + pay(side, Kh, S), 2)


def settlement(exp, G=get):
    cs = G("/v2/history/candles", {"resolution": "1m", "symbol": "BTCUSD", "start": exp - 1800, "end": exp})
    cs = sorted([c for c in cs if int(c["time"]) < exp], key=lambda c: int(c["time"]))
    if len(cs) < 20:
        return None
    return sum(float(c["close"]) for c in cs[-30:]) / len(cs[-30:])


def read(f):
    return list(csv.DictReader(open(f))) if os.path.exists(f) else []


def append(f, fields, row):
    new = not os.path.exists(f)
    os.makedirs(OUT, exist_ok=True)
    with open(f, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(fields)
        w.writerow(["" if row.get(k) is None else row.get(k) for k in fields])


def settle(now, G=get):
    done = {(r["exp_ts"], r["side"], r["thr"]) for r in read(OUTC)}
    n, cache = 0, {}
    for r in read(TRG):
        exp = int(r["exp_ts"])
        if (r["exp_ts"], r["side"], r["thr"]) in done or now < exp + 300:
            continue
        if exp not in cache:
            cache[exp] = settlement(exp, G)
        S = cache[exp]
        if S is None:
            continue
        sd = r["side"]
        o = dict(r); o["S"] = round(S, 1)
        o["A1"] = variant(sd, r["bid_same"], r["K"], r["ask_old"], r["Kh"], S)
        o["A2"] = variant(sd, r["bid_same"], r["K"], r["ask_newh"], r["Khn"], S)
        o["B1"] = variant(sd, r["bid_new"], r["Kn"], r["ask_old"], r["Kh"], S)
        o["B2"] = variant(sd, r["bid_new"], r["Kn"], r["ask_newh"], r["Khn"], S)
        append(OUTC, OF, o); n += 1
    return n


def report():
    rows = read(OUTC)
    print("ADD PAPER LOG: %d settled triggers on %d nights (real Delta quotes; USD per 1 BTC of option)" % (len(rows), len({r["exp_ts"] for r in rows})))
    names = dict(A1="same strike + old hedge", A2="same strike + new hedge", B1="new strike + old hedge", B2="new strike + new hedge")
    for thr in THR:
        for early in (True, False):
            rr = [r for r in rows if abs(float(r["thr"]) - thr) < 1e-9 and (float(r["mins"]) <= 180) == early]
            if not rr:
                continue
            print("trigger %.1f%%, %s: %d" % (thr, "within 3 h (to 02:30)" if early else "3 to 6 h", len(rr)))
            for v in ("A1", "A2", "B1", "B2"):
                xs = [float(r[v]) for r in rr if r[v] not in ("", None)]
                if xs:
                    print("   %s %-24s n %3d  total %+9.1f  avg %+8.2f  won %3.0f%%  worst %+9.1f" % (v, names[v], len(xs), sum(xs), sum(xs) / len(xs), 100.0 * sum(1 for x in xs if x > 0) / len(xs), min(xs)))


def run(now=None, G=get, live=live_strikes):
    now = time.time() if now is None else now
    os.makedirs(OUT, exist_ok=True)
    try:
        st = json.load(open(STF))
    except Exception:
        st = None
    exp = next_expiry(now)
    if not st or st.get("exp") != exp:
        a = anchor(now, G, live)
        if a:
            st = a; json.dump(st, open(STF, "w"))
    if st and st.get("exp") == exp:
        rows = check(st, now, G)
        for r in rows:
            append(TRG, TF, r)
        if rows:
            json.dump(st, open(STF, "w"))
    return settle(now, G)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        report()
    else:
        try:
            run()
        except Exception as e:
            print("%s addpaper: %s: %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M"), type(e).__name__, str(e)[:200]))
