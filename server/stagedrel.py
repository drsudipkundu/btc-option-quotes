#!/usr/bin/env python3
"""stagedrel - c18 EMERGENCY STAGED MARGIN RELEASE, REPORT ONLY (built 26-Nov-2026, Sudip's spec of 00:41 to 15:35 IST).
It only sends GET requests. It NEVER places an order, never moves money, never changes a setting. It tells Sudip on Telegram and Gmail
what it WOULD cut in the night sell (serverbot) and what it WOULD move to the ladder account (ladder9), so the numbers can be checked first.

What it watches (every 2 minutes, only while a night position is open):
 1. Ladder9 equity now (Delta: available + blocked margin).
 2. WINDOW test: BTC falls window_pct (5 %) from the CURRENT price. The v9 ladder buys at its own grid levels inside that window (zones and gaps,
    last buy read from the LIFO of its own fills, brake limit). Need = margin of what it would hold at the bottom + loss on the way down
    + margin of the call that may be short. Same walk-down as sweep_report.py, only the window is different. If the ladder would buy nothing
    inside the window, the need is just what it holds now.
 3. Gap = need - equity. Gap <= 0: the bot only looks and sleeps (today's case: plenty of money).
 4. Gap > 0: plan which night legs to cut to free that much margin (plus a small cushion), in Sudip's order: put, call, put, call, ...
      puts : by quantity, bigger first: the top-up quantity, then 50 %, 30 %, 20 % of the small base (numbers are settings)
      calls: by decay: a call that has decayed x % releases x % of its quantity
      the far (hedge) options stay. If a tier cannot free enough, it goes to the next leg at once. If everything is not enough: ALERT.
 5. Money it WOULD move from serverbot to ladder9 = the gap + cushion (limited by serverbot's own available money). The daily or weekly
    sweep cap is NOT applied to an emergency (setting ignore_cap, default true) but the message shows what the cap would have allowed.

Margin freed per BTC cut (rough fit on 10,732 minute rows of the margin log, R2 0.976): 0.0048 x spot (put) or 0.0050 x spot (call) + 1.2375 x the option's mark.
NEVER IGNORE (Sudip 26-Nov 15:34): the ladder zones and gaps used here are a COPY (sweep_report.py settings) while the ladder runs in Tradetron.
Every message prints the zone values used. When the ladder runs on the server, read them from the ladder's own state and delete the copy.

  venv/bin/python stagedrel.py                  run (cron every 2 minutes): log to logs/stagedrel.csv, Telegram + Gmail when it would act
  venv/bin/python stagedrel.py --show           run and only print (no Telegram, no log)
  venv/bin/python stagedrel.py --show --fake-equity 3000    DRY RUN: pretend the ladder holds 3000 USD, to see the plan
Settings in state/stagedrel_cfg.json (only the keys you list change). No order code exists in this file."""
import os, sys, csv, json, math, time, datetime as dt

H = os.path.expanduser(os.environ.get("BOT_HOME", "~/deltabot"))
sys.path.insert(0, H)
STATE = os.path.join(H, "state"); LOGS = os.path.join(H, "logs")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
C = 0.001                                           # BTC per contract

CFG = dict(
    window_pct=5.0, buffer=1.0, cushion_pct=5.0, cushion_min_usd=20.0,
    put_tiers=[0.5, 0.3, 0.2],                      # after the top-up quantity: share of the small base put quantity
    min_call_decay=0.05,                            # a call decayed less than this releases nothing
    m_put=0.0048, m_call=0.0050, m_mark=1.2375,     # margin per BTC cut: m x spot + m_mark x option mark
    ignore_cap=True, cap_inr=100000.0, fx=85.0,
    topup_after_min=10,                             # a sold leg opened more than this many minutes after the first sale of its side is a top-up
    repeat_min=30,                                  # same plan is not sent again within this many minutes
)


def jl(p, d=None):
    try:
        return json.load(open(p))
    except Exception:
        return {} if d is None else d


def load_cfg():
    c = dict(CFG)
    c.update(jl(os.path.join(STATE, "stagedrel_cfg.json")))
    return c


def fx_(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def rs(u, fx=85.0):
    return "Rs %s" % format(int(round(u * fx, -1)), ",")


# ------------------------------------------------------------------ the need for a fall window (pure, testable)
def need_window(SR, c, spot, H0, last_buy, r_fut, call_btc, window_pct):
    """USD the ladder needs to survive a fall of window_pct from spot: margin at the bottom + loss on the way down + call margin."""
    Pst = spot * (1 - window_pct / 100.0)
    hold = H0; loss = H0 * (spot - Pst); nlots = 0
    for lvl in SR.grid_levels(c):
        if lvl >= last_buy or lvl < Pst:
            continue
        if hold + c["lot_btc"] > c["brake_btc"] + 1e-9:
            break
        hold += c["lot_btc"]; loss += c["lot_btc"] * (lvl - Pst); nlots += 1
    margin = r_fut * hold * Pst + c["call_ratio"] * call_btc * Pst
    return dict(Pst=Pst, hold=hold, nlots=nlots, margin=margin, loss=loss, need=margin + loss)


# ------------------------------------------------------------------ the cutting plan (pure, testable)
def freed_per_btc(c, side, spot, mark):
    return (c["m_put"] if side == "PE" else c["m_call"]) * spot + c["m_mark"] * mark


def classify(legs, c):
    """add leg['cls'] = 'base' or 'topup' (a leg opened well after the first sale of its side)"""
    first = {}
    for l in legs:
        t = dt.datetime.fromisoformat(l["t"]).timestamp()
        first[l["side"]] = min(first.get(l["side"], t), t)
    for l in legs:
        t = dt.datetime.fromisoformat(l["t"]).timestamp()
        l["cls"] = "topup" if t - first[l["side"]] > c["topup_after_min"] * 60 else "base"
    return legs


def plan_cuts(c, spot, legs, marks, need_usd):
    """legs: open SOLD main legs (dicts: id, side PE/CE, sym, qty BTC, entry, t). marks: {sym: mark price}.
    Returns dict(steps=[...], freed, short) - steps are (label, leg id, sym, side, qty BTC, freed USD)."""
    legs = classify([dict(l) for l in legs], c)
    rem = {l["id"]: round(l["qty"], 6) for l in legs}
    put_base = sum(l["qty"] for l in legs if l["side"] == "PE" and l["cls"] == "base")
    steps, freed = [], 0.0

    def take(label, side, want, cls=None, decay=False):
        nonlocal freed
        got = 0.0
        for l in sorted([x for x in legs if x["side"] == side and (cls is None or x["cls"] == cls)], key=lambda x: -x["id"]):
            if freed >= need_usd - 1e-9:
                break
            mk = marks.get(l["sym"], 0.0)
            q = rem[l["id"]]
            if decay:
                d = 1.0 - (mk / l["entry"] if l["entry"] else 1.0)
                if d < c["min_call_decay"]:
                    continue
                q = q * d
            q = min(q, want - got) if want is not None else q
            q = math.floor(q / C + 1e-9) * C                       # whole contracts
            if q < C - 1e-12:
                continue
            fb = freed_per_btc(c, side, spot, mk)
            if freed + q * fb > need_usd:                          # last cut: only as much as needed (whole contracts, rounded up)
                q = min(q, math.ceil(max(need_usd - freed, 0) / fb / C - 1e-9) * C)
            if q < C - 1e-12:
                continue
            rem[l["id"]] = round(rem[l["id"]] - q, 6)
            steps.append((label, l["id"], l["sym"], side, round(q, 3), q * fb))
            freed += q * fb; got += q
            if want is not None and got >= want - 1e-12:
                break
        return got

    turns = [("put top-up", "PE", None, "topup", False)] + [("put %d%% of base" % round(t * 100), "PE", t * put_base, "base", False) for t in c["put_tiers"]]
    for i, (lab, side, want, cls, dec) in enumerate(turns):
        if freed >= need_usd - 1e-9:
            break
        take(lab, side, want, cls, dec)
        if freed >= need_usd - 1e-9:
            break
        take("call by decay", "CE", None, None, True)             # after every put turn, the call turn
    return dict(steps=steps, freed=freed, short=max(need_usd - freed, 0.0))


# ------------------------------------------------------------------ main calculation
def compute(c, Live, Pub, fake_eq=None):
    import sweep_report as SR
    sc = SR.load_cfg()
    pub = Pub()
    tk = pub._http("GET", "/v2/tickers/BTCUSD")["result"]
    spot = SR.f(tk.get("spot_price")) or SR.f(tk.get("mark_price"))
    lcl, L = SR.read_acct(Live, "ladder9")
    scl, S = SR.read_acct(Live, "serverbot")
    fut = [p for p in L["pos"] if str(p.get("product_symbol")) == "BTCUSD"]
    H0 = sum(SR.f(p.get("size")) for p in fut) / SR.CPB
    fm = sum(SR.f(p.get("margin")) for p in fut)
    r_fut = fm / (H0 * spot) if H0 > 0 and spot > 0 and fm > 0 else sc["fut_ratio_default"]
    calls = [p for p in L["pos"] if str(p.get("product_symbol", "")).startswith("C-") and SR.f(p.get("size")) < 0]
    call_btc = sum(abs(SR.f(p.get("size"))) for p in calls) / SR.CPB
    if not sc.get("calls_on", True):
        call_btc = 0.0
    elif not calls:
        call_btc = H0
    last_buy, lb_note = None, "no ladder position"
    if H0 > 0:
        try:
            last_buy, lb_note = SR.lifo_last_buy(lcl, int(tk.get("product_id")), sc["since"], int(round(H0 * SR.CPB)))
        except Exception as e:
            lb_note = "fills not read (%s) -> worst case used" % type(e).__name__
    if last_buy is None:
        last_buy = spot * 1.0001
    w = need_window(SR, sc, spot, H0, last_buy, r_fut, call_btc, c["window_pct"])
    need_usd = w["need"] * c["buffer"]
    eq = L["equity_usd"] if fake_eq is None else float(fake_eq)
    gap = need_usd - eq
    # night legs (the live bot's own state file)
    st = jl(os.path.join(STATE, "night_nlive.json"))
    legs = [l for l in (st.get("legs") or []) if l.get("dir") == "S" and not l.get("closed") and l.get("kind") != "ins"]
    marks = {}
    for l in legs:
        try:
            marks[l["sym"]] = SR.f(pub._http("GET", "/v2/tickers/%s" % l["sym"])["result"].get("mark_price"))
        except Exception:
            marks[l["sym"]] = 0.0
    d = dict(c=c, sc=sc, spot=spot, H0=H0, r_fut=r_fut, call_btc=call_btc, last_buy=last_buy, lb_note=lb_note, w=w, need_usd=need_usd, eq=eq, gap=gap,
             fake=fake_eq is not None, legs=legs, marks=marks, s_avail=S["avail"], night=st.get("night"), plan=None, move_usd=0.0)
    if gap > 0 and legs:
        cush = max(gap * c["cushion_pct"] / 100.0, c["cushion_min_usd"])
        d["target"] = gap + cush
        d["plan"] = plan_cuts(c, spot, legs, marks, d["target"])
        d["move_usd"] = min(gap + cush, S["avail"] + d["plan"]["freed"])
    return d


def message(d):
    c, w = d["c"], d["w"]
    fx = c["fx"]
    tag = "EMERGENCY STAGED RELEASE (report only - nothing was cut or moved)" + (" - DRY RUN with a pretend ladder balance" if d["fake"] else "")
    L = [tag + " %s IST" % dt.datetime.now(IST).strftime("%d-%b %H:%M"),
         "BTC %.0f. Ladder9 holds %.3f BTC (margin ratio %.2f), call reserved %.3f BTC." % (d["spot"], d["H0"], d["r_fut"], d["call_btc"]),
         "WINDOW %.1f%% fall to %.0f: ladder would hold %.3f BTC (+%d lots), needs %s." % (c["window_pct"], w["Pst"], w["hold"], w["nlots"], rs(d["need_usd"], fx)),
         "Ladder9 equity %s. %s." % (rs(d["eq"], fx), ("GAP %s" % rs(d["gap"], fx)) if d["gap"] > 0 else "Covers the window with %s to spare: only watching" % rs(-d["gap"], fx))]
    if d["gap"] > 0:
        if not d["legs"]:
            L.append("There is a gap but no night position is open: nothing to cut (the 18:15 sweep handles the balance).")
        else:
            p = d["plan"]
            L.append("WOULD CUT (hedge stays), target %s incl. cushion:" % rs(d["target"], fx))
            for lab, lid, sym, side, q, fr in p["steps"]:
                L.append("  %s: buy back %.3f BTC of %s (leg %d), frees about %s" % (lab, q, sym, lid, rs(fr, fx)))
            L.append("Frees about %s in total." % rs(p["freed"], fx))
            if p["short"] > 0:
                L.append("ALERT: everything allowed is not enough, still short %s. Fall bigger than planned: different math needed." % rs(p["short"], fx))
            cap = c["cap_inr"] / fx
            L.append("WOULD MOVE %s from serverbot to Ladder9 (serverbot available now %s). %s" % (
                rs(d["move_usd"], fx), rs(d["s_avail"], fx),
                "Cap ignored for an emergency (setting ignore_cap); the sweep cap %s would have limited it." % rs(cap, fx) if c["ignore_cap"] else
                "Limited by the cap %s." % rs(cap, fx)))
    sc = d["sc"]
    L.append("Zone values used (a COPY, keep equal to the live v9): entry %.1f, gaps %.2f/%.2f/%.2f/%.2f %%, zones %.2f/%.2f/%.2f %%, lot %.3f, brake %.2f BTC. Basis: %s." % (
        sc["entry"], sc["gap_pct"], sc["gap3_pct"], sc["gap4_pct"], sc["gap5_pct"], sc["z2_lo_pct"], sc["z3_lo_pct"], sc["z4_lo_pct"], sc["lot_btc"], sc["brake_btc"], d["lb_note"]))
    L.append("REPORT ONLY: no order was placed and no money was moved.")
    return "\n".join(L)


def bot_off(name):
    """26-Nov-2026: Telegram /stop <bot> sets a flag in state/bots_off.json; the scheduled run then does nothing until /go <bot>"""
    try:
        return bool(json.load(open(os.path.join(STATE, "bots_off.json"))).get(name))
    except Exception:
        return False


def main():
    show = "--show" in sys.argv
    if not show and bot_off("emergency"):
        json.dump(dict(t=time.time(), text="emergency bot: STOPPED by you (Telegram /go emergency starts it again)"), open(os.path.join(STATE, "stagedrel_status.json"), "w"))
        return
    fake = None
    if "--fake-equity" in sys.argv:
        fake = float(sys.argv[sys.argv.index("--fake-equity") + 1])
    c = load_cfg()
    st = jl(os.path.join(STATE, "night_nlive.json"))
    has_pos = any(l.get("dir") == "S" and not l.get("closed") and l.get("kind") != "ins" for l in (st.get("legs") or []))
    status = os.path.join(STATE, "stagedrel_status.json")
    if not has_pos and fake is None:
        if not show:
            json.dump(dict(t=time.time(), text="emergency bot: no night position open, nothing to watch"), open(status, "w"))
        else:
            print("no night position open: nothing to watch (use --fake-equity only with a position open)")
        return
    from liveorders import Live, Pub
    try:
        d = compute(c, Live, Pub, fake)
    except Exception as e:
        t = "EMERGENCY STAGED RELEASE check failed: %s: %s. Nothing cut, nothing moved." % (type(e).__name__, str(e)[:200])
        print(t)
        if not show:
            import sweep_report as SR
            if time.time() - jl(os.path.join(STATE, "stagedrel_state.json")).get("fail_t", 0) > 3600:
                SR.tg(t); json.dump(dict(fail_t=time.time()), open(os.path.join(STATE, "stagedrel_state.json"), "w"))
        return
    msg = message(d)
    print(msg)
    if show:
        return
    os.makedirs(LOGS, exist_ok=True)
    cover = ("covers %.1f%% fall with %s to spare" % (c["window_pct"], rs(-d["gap"], c["fx"]))) if d["gap"] <= 0 else ("GAP %s (would cut/move, report only)" % rs(d["gap"], c["fx"]))
    json.dump(dict(t=time.time(), text="emergency bot watching: ladder %s" % cover), open(status, "w"))
    p = os.path.join(LOGS, "stagedrel.csv"); new = not os.path.exists(p)
    with open(p, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["time_ist", "spot", "ladder_eq_usd", "need_usd", "gap_usd", "freed_usd", "short_usd", "move_usd", "steps"])
        pl = d["plan"] or dict(steps=[], freed=0, short=0)
        w.writerow([dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), round(d["spot"], 1), round(d["eq"], 2), round(d["need_usd"], 2), round(d["gap"], 2),
                    round(pl["freed"], 2), round(pl["short"], 2), round(d["move_usd"], 2), ";".join("%s %.3f" % (s[0], s[4]) for s in pl["steps"])])
    if d["gap"] > 0 and d["legs"]:
        import sweep_report as SR
        sf = os.path.join(STATE, "stagedrel_state.json"); s = jl(sf)
        sig = "%s|%s" % (d["night"], ";".join("%s%.3f" % (x[0], x[4]) for x in d["plan"]["steps"]))
        if sig != s.get("sig") or time.time() - s.get("t", 0) > c["repeat_min"] * 60:
            SR.tg(msg); SR.email("[DeltaBot] EMERGENCY staged release (report only) %s" % dt.datetime.now(IST).strftime("%d-%b %H:%M"), msg)
            json.dump(dict(sig=sig, t=time.time()), open(sf, "w"))


if __name__ == "__main__":
    main()
