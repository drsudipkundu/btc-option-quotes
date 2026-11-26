#!/usr/bin/env python3
"""reports.py - scheduled Telegram + Gmail reports for the BTC night sell (25-Nov-2026 c16, Sudip's request).
READ-ONLY: it reads the bot's state files and public prices; it never places, changes or cancels an order and never changes a setting.

  python reports.py plan       22:00  tonight's plan: sales ON/OFF, settings, preview, SIZE CALCULATION (small and big base, with the logic)
  python reports.py decision   23:33  what the bot decided and sold at 23:30, with the size logic and the hedges
  python reports.py position   23:50  executed position: every leg, hedge cover, top-up, expected profit (3 ways), worst case
  python reports.py status     07:00 and 17:22  status: open profit, earned share, settings, expected profit, daily result
  python reports.py watch      every minute: after the position changes (sale, hedge, top-up, exit, failure) and stays quiet for 2 minutes, one status
  python reports.py show NAME  print a report, send nothing

Every report goes to Telegram and to Gmail. Each part is wrapped so one failed number never stops the report."""
import os, sys, json, time, math, datetime as dt

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
FX = 85.0                                  # Rs per USD for display (Sudip's rule: Rs with USD at 85)
MOVED_HV, SL_THR, SL_CUT = 0.28347, 0.123, 0.5   # same numbers as nightlogic.py (overridden from it when importable)
try:
    import nightlogic as _NL
    MOVED_HV, SL_THR, SL_CUT = _NL.MOVED_HV, _NL.SL_THR, _NL.SL_CUT
except Exception:
    pass


def jl(p, d=None):
    try:
        return json.load(open(os.path.join(HOME, p)))
    except Exception:
        return {} if d is None else d


def rs(u):
    return "Rs %s" % format(int(round(float(u) * FX, -1)), ",")


def usd(x):
    return "%+.2f USD (%s)" % (x, rs(x))


def part(fn, *a):
    """run one part of a report; a failure becomes one short line, never a missing report"""
    try:
        return fn(*a)
    except Exception as e:
        return "(%s not available: %s)" % (getattr(fn, "__name__", "part"), type(e).__name__)


def floor001(x):
    return int(max(0.0, x) / 0.01 + 1e-9) / 100.0


def sold_legs(S):
    return [l for l in S.get("legs", []) if l.get("dir") == "S" and l.get("kind") != "ins"]


def wing_legs(S):
    return [l for l in S.get("legs", []) if l.get("dir") == "B" and l.get("kind") == "wing"]


def cover_qty(S, leg):
    return sum(w["qty"] for w in wing_legs(S) if w.get("cover") == leg["id"] and not w.get("closed"))


# ---------------------------------------------------------------- settings and sales state
def settings_text():
    c = jl("state/night_live_cfg.json")
    j = float(c.get("juice") or 0)
    tp = "OFF" if not j else ("close now" if j >= 5 else "closes at %.0f %% of premium earned (%s)" % (100 - j * 100, "this night only" if c.get("juice_once") else "every night"))
    sm = float(c.get("size_mult", 1) or 1)
    return ("Settings: take-profit %s | caution %s | size x%s | hedge %s | retry hedge limit %s | flags mode %s"
            % (tp, "ON tonight" if c.get("caution") else "off", ("%.2f (next sale only)" % sm) if 0 < sm < 1 else "1",
               ("%.0f %% beyond" % (float(c.get("wing") or 0) * 100)) if c.get("wing") else "OFF",
               "on" if c.get("retry_lim", 1) else "off", str(c.get("flagmode", "off")).upper()))


def sales_state():
    """(text, ok) - are tonight's sales going to run"""
    c, S = jl("state/night_live_cfg.json"), jl("state/night_nlive.json")
    why = []
    try:
        import control
        st = control.get("nlive")["state"]
        if st != "running":
            why.append("state is %s (after /exit or /pause)" % st)
    except Exception:
        pass
    if os.path.exists(os.path.join(HOME, "STOP")) or os.path.exists(os.path.join(HOME, "state", "STOP")):
        why.append("the STOP file exists")
    if not c.get("armed"):
        why.append("the bot is not armed")
    if S.get("halt"):
        why.append("HALT: %s" % str(S["halt"])[:120])
    if why:
        return "SALES ARE OFF tonight: " + "; ".join(why) + ". Send /resume (or /clearhalt) and then /status before 23:30.", False
    return "Sales are ON: armed, state running, no halt. The sale starts at 23:30 IST.", True


# ---------------------------------------------------------------- size logic (the calculation behind small base / big base)
def size_logic():
    import autosize as A, sizecalc as SC
    c = jl("state/night_live_cfg.json")
    st = jl("state/autosize.json")
    wallet, spot, open_pos, safe, fx, _tg, safe_big = A.read_all()
    ind = SC.tonight_ind()
    live, big_cfg = float(c.get("base", 0)), float(c.get("base_big") or 0)
    ceil_on = bool(st.get("ceiling")) and time.time() >= st.get("ceiling_from_ts", 0)
    maxb = float(st["ceiling"]) if ceil_on else float(st.get("max_base") or live)
    small = min(floor001(wallet / safe * 0.01), maxb)
    big = max(0.0, min(floor001(wallet / safe_big * 0.01), maxb))
    L = ["SIZE CALCULATION (BTC %.0f)" % spot,
         "Balance %.0f USD (%s). Money needed per 0.01 BTC of base: %.0f USD (%s) for the SMALL base (crash-guard stress on the biggest night),"
         " %.0f USD (%s) for the BIG base (once every far option is bought)." % (wallet, rs(wallet), safe, rs(safe), safe_big, rs(safe_big)),
         "Small base = balance / %.0f x 0.01 = %.3f -> rounded down %.2f BTC. Big base = balance / %.0f x 0.01 = %.3f -> rounded down %.2f BTC."
         % (safe, wallet / safe * 0.01, floor001(wallet / safe * 0.01), safe_big, wallet / safe_big * 0.01, floor001(wallet / safe_big * 0.01)),
         "Ceiling %s -> allowed small %.2f, big %.2f. Live now: small %.2f, big %.2f (the first sale uses the small base; the top-up lifts a side to the big base only if every far option of that side is bought within 1 hour)."
         % (("%.2f BTC" % maxb) if ceil_on else "none (your armed base %.2f)" % maxb, small, big, live, big_cfg)]
    hv14, hv365 = ind.get("hv14"), ind.get("hv365")
    if hv14 is not None:
        moved = hv14 > MOVED_HV
        slope = ind.get("sl_acc") is not None and ind["sl_acc"] > SL_THR
        L.append("Rules tonight: HV14 %.3f %s %.3f -> %s night: trend leg x%d. %s Opposite leg: %s. Slope: %s."
                 % (hv14, ">" if moved else "<=", MOVED_HV, "MOVED" if moved else "normal", 3 if moved else 1,
                    "(quiet-night sale only if the day's range is big enough)" if not moved else "",
                    "x1 (HV14 %.3f >= HV365 %.3f)" % (hv14, hv365) if (hv365 is not None and hv14 >= hv365) else "not sold (HV14 below HV365)",
                    "speeding up -> base HALVED (x%.1f)" % SL_CUT if slope else "normal (x1)"))
    return "\n".join(L)


def decision_logic(S):
    """after the sale: the factors behind the quantities the bot really sold"""
    c = jl("state/night_live_cfg.json")
    base = float(c.get("base", 0))
    pl = S.get("plan") or {}
    fn = S.get("flags_night") or {}
    fm = fn.get("mult", S.get("rich_mult", 1) if S.get("rich_night") == S.get("night") else 1)
    out = []
    try:
        import sizecalc as SC
        ind = SC.tonight_ind()
        moved = ind["hv14"] > MOVED_HV
        out.append("Trend leg %.3f BTC = small base %.2f x %d (%s night, HV14 %.3f vs %.3f) x flags %.2f (premium %s, volatility %s, RSI %s)%s"
                   % (float(pl.get("trend", 0)), base, 3 if moved else 1, "moved" if moved else "normal", ind["hv14"], MOVED_HV, float(fm or 1),
                      "on" if fn.get("P") else "off", "on" if fn.get("V") else "off", "on" if fn.get("R") else "off",
                      "" if abs(base * (3 if moved else 1) * float(fm or 1) - float(pl.get("trend", 0))) < 1e-6 else " (the bot's own figure also includes slope-half or rounding)"))
    except Exception:
        out.append("Trend leg %.3f BTC, flags x%s (details of today's volatility not available)" % (float(pl.get("trend", 0)), fm))
    if pl.get("extra"):
        out.append("Opposite leg %.3f BTC = base %.2f x 1 (HV14 at or above HV365)" % (float(pl["extra"]), base))
    bb = float(c.get("base_big") or 0)
    td = S.get("topup_sides") or {}
    if bb > base + 1e-9:
        done = td.get("sides", []) if td.get("night") == S.get("night") else []
        out.append("Top-up: each side is lifted to the big base %.2f (x %.2f of what was sold) once all its far options are bought within 1 hour; done for: %s"
                   % (bb, bb / base if base else 0, ", ".join(done) or "none yet"))
    return "\n".join(out)


# ---------------------------------------------------------------- position and expected profit
def position_block(S):
    sold = [l for l in sold_legs(S) if not l.get("closed")]
    if not sold:
        return "No sold option is open."
    rows = []
    for side in ("PE", "CE"):
        ls = [l for l in sold if l["side"] == side]
        if not ls:
            continue
        q = sum(l["qty"] for l in ls)
        avg = sum(l["entry"] * l["qty"] for l in ls) / q
        cov = sum(cover_qty(S, l) for l in ls)
        ws = [w for w in wing_legs(S) if w.get("side") == side and not w.get("closed")]
        wq = sum(w["qty"] for w in ws)
        wavg = (sum(w["entry"] * w["qty"] for w in ws) / wq) if wq else 0
        ins = [l for l in S.get("legs", []) if l.get("kind") == "ins" and l["side"] == side and not l.get("closed")]
        rows.append("%s: SOLD %d contracts (%.3f BTC) @ %.1f avg, strike %s | HEDGE %s | %s"
                    % ("PUT" if side == "PE" else "CALL", round(q * 1000), q, avg,
                       "/".join(sorted(set(str(int(l["strike"])) for l in ls))),
                       ("%d contracts @ %.1f avg (strike %s) covers %.0f %% of the sold quantity" % (round(wq * 1000), wavg, "/".join(sorted(set(str(int(w["strike"])) for w in ws))), 100 * cov / q)) if wq else "NONE",
                       "crash-guard insurance bought" if ins else "no insurance leg"))
    return "\n".join(rows)


def expected_block(S):
    legs = S.get("legs", [])
    booked = sum(float(l.get("pnl") or 0) for l in legs if l.get("closed")) + sum(float(l.get("pnl_part") or 0) for l in legs if not l.get("closed"))
    osold = [l for l in sold_legs(S) if not l.get("closed")]
    owing = [w for w in wing_legs(S) if not w.get("closed")]
    fees_open = sum(float(l.get("fee") or 0) for l in osold + owing)
    ifexp = booked + sum(l["entry"] * l["qty"] for l in osold) - sum(w["entry"] * w["qty"] for w in owing) - fees_open
    credit = sum(l["entry"] * l["qty"] for l in sold_legs(S)) - sum(w["entry"] * w["qty"] for w in wing_legs(S))
    j = float(jl("state/night_live_cfg.json").get("juice") or 0)
    L = ["EXPECTED PROFIT (bot's own prices; fees included)",
         "Net premium of the night (sold minus hedges) %.2f USD (%s)." % (credit, rs(credit)),
         "1) If everything expires worthless: %s" % usd(ifexp)]
    if 0 < j < 5 and credit > 0:
        L.append("2) At your take-profit (%.0f %% of the premium earned): about %s" % (100 - j * 100, usd(booked + (1 - j) * credit - fees_open)))
    for side in ("PE", "CE"):
        ls = [l for l in osold if l["side"] == side]
        if not ls:
            continue
        cl = [l for l in ls if cover_qty(S, l) > 0]
        if not cl:
            continue
        wk = {}
        for w in owing:
            if w["side"] == side:
                wk[w["strike"]] = wk.get(w["strike"], 0) + w["qty"]
        width = sum(abs(l["strike"] - min(wk, key=lambda k: abs(k - l["strike"]))) * min(l["qty"], cover_qty(S, l)) for l in cl) if wk else 0
        cred = sum(l["entry"] * l["qty"] for l in ls) - sum(w["entry"] * w["qty"] for w in owing if w["side"] == side)
        L.append("3) Theoretical maximum loss on the %s side (BTC ends beyond the far option and nothing else acted): -%.2f USD = spread width x quantity %.2f minus this side's premium %.2f. The crash guard normally acts much earlier; the uncovered part is left to it."
                 % ("put" if side == "PE" else "call", width - cred, width, cred))
    return "\n".join(L)


def daily_block(S):
    ln = S.get("last_night") or {}
    L = []
    if ln:
        L.append("Last finished night %s: %s" % (ln.get("night"), usd(float(ln.get("pnl", 0)))))
    if "total_pnl" in S:
        L.append("Running total %s over %s nights" % (usd(float(S["total_pnl"])), S.get("nights", "?")))
    return " | ".join(L)


def earned_block(S):
    """share of the night's premium earned so far, from live prices (same idea as the take-profit rule)"""
    import tgplus as T
    legs = [l for l in S.get("legs", []) if not l.get("closed")]
    if not legs:
        return ""
    credit = sum(l["entry"] * l["qty"] for l in sold_legs(S)) - sum(w["entry"] * w["qty"] for w in wing_legs(S))
    left = 0.0
    for l in legs:
        b, a, m, _s = T._tk(l["sym"])
        if l["dir"] == "S":
            left += (a or m) * l["qty"]
        elif l.get("kind") == "wing":
            left -= (b or m) * l["qty"]
    if credit <= 0:
        return ""
    return "Earned so far: %.0f %% of the night's premium (still to gain by holding %.2f USD of %.2f)." % (max(0.0, (1 - max(0.0, left) / credit)) * 100, max(0.0, left), credit)


# ---------------------------------------------------------------- the reports
def plan_report():
    import tgplus as T
    S = jl("state/night_nlive.json")
    L = ["PLAN %s IST - tonight's sale at 23:30" % dt.datetime.now(IST).strftime("%d-%b %H:%M"), sales_state()[0], part(settings_text)]
    op = [l for l in S.get("legs", []) if not l.get("closed")]
    if op:
        L.append("NOTE: a position from the last night is still open (%d legs); no new sale until it is closed." % len(op))
    L.append(part(T.tonight_text))
    L.append(part(size_logic))
    L.append(part(daily_block, S))
    return "\n\n".join(x for x in L if x)


def decision_report():
    S = jl("state/night_nlive.json")
    now = dt.datetime.now(IST)
    L = ["DECISION %s IST - what the bot did at 23:30" % now.strftime("%d-%b %H:%M")]
    sold = sold_legs(S)
    today = now.strftime("%Y-%m-%d")
    if not sold or S.get("night") != today:
        L.append("NO SALE has happened tonight. " + sales_state()[0])
        L.append(part(settings_text))
        return "\n\n".join(L)
    L.append(part(position_block, S))
    L.append(part(decision_logic, S))
    L.append(part(settings_text))
    return "\n\n".join(L)


def position_report(title="POSITION"):
    S = jl("state/night_nlive.json")
    now = dt.datetime.now(IST)
    L = ["%s %s IST" % (title, now.strftime("%d-%b %H:%M")), part(position_block, S)]
    if [l for l in S.get("legs", []) if not l.get("closed")]:
        L.append(part(decision_logic, S))
        L.append(part(expected_block, S))
        L.append(part(earned_block, S))
    elif not sold_legs(S) or S.get("night") != now.strftime("%Y-%m-%d"):
        L.append(sales_state()[0])
    L.append(part(settings_text))
    L.append(part(daily_block, S))
    return "\n\n".join(x for x in L if x)


def emergency_block():
    """c19: one line from the emergency staged-release bot (stagedrel.py, c18). Silence from it would be ambiguous, so this says it is alive."""
    d = jl("state/stagedrel_status.json")
    if not d or not d.get("text"):
        return "EMERGENCY BOT (staged margin release): no check recorded yet (c18 not installed, or no night position has been open since)."
    age = (time.time() - float(d.get("t", 0))) / 60.0
    txt = d["text"]
    if age > 15 and "no night position" not in txt:
        return "EMERGENCY BOT: WARNING last check was %.0f minutes ago (should be every 2 minutes): %s" % (age, txt)
    return "EMERGENCY BOT (report only): %s (checked %.0f min ago)." % (txt, age)


def status_report():
    import tgplus as T
    S = jl("state/night_nlive.json")
    now = dt.datetime.now(IST)
    L = ["STATUS %s IST" % now.strftime("%d-%b %H:%M")]
    if [l for l in S.get("legs", []) if not l.get("closed")]:
        L.append(part(T.pnl_text))
        L.append(part(position_block, S))
        L.append(part(earned_block, S))
        L.append(part(expected_block, S))
        L.append("The night expires at 17:30 IST; the bot buys back whatever is left at 17:20.")
    else:
        L.append("No position is open.")
        L.append(sales_state()[0])
    L.append(part(emergency_block))
    L.append(part(settings_text))
    L.append(part(daily_block, S))
    return "\n\n".join(x for x in L if x)


REPORTS = dict(plan=plan_report, decision=decision_report, position=position_report, status=status_report)


# ---------------------------------------------------------------- sending
def send(subject, text):
    ok = []
    try:
        import nightwatch as NW
        for i in range(0, len(text), 3800):
            NW.tg_send(text[i:i + 3800])
        ok.append("telegram")
    except Exception as e:
        print("telegram failed:", type(e).__name__)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HOME, ".env"))
        import bot as B
        B.Notifier()._send_now("[DeltaBot LIVE] REPORT " + subject, text)
        ok.append("gmail")
    except Exception as e:
        print("gmail failed:", type(e).__name__)
    return ok


def watch():
    """after the position changes and stays quiet for 2 minutes -> one status (telegram + gmail). Quiet when nothing is open and nothing changed."""
    S = jl("state/night_nlive.json")
    legs = S.get("legs", [])
    sig = "%s|%d|%d|%d|%s" % (S.get("night"), len(legs), sum(1 for l in legs if l.get("closed")), round(sum(l["qty"] for l in legs if not l.get("closed")) * 1000), S.get("halt") or "")
    p = os.path.join(HOME, "state", "reports_seen.json")
    w = jl("state/reports_seen.json")
    now = time.time()
    if w.get("sig") != sig:
        w.update(sig=sig, changed=now, sent=False)
        if "first" not in w:                          # first ever run: remember, say nothing
            w.update(first=now, sent=True)
        json.dump(w, open(p + ".tmp", "w")); os.replace(p + ".tmp", p)
        return "changed"
    if not w.get("sent") and now - w.get("changed", now) >= 120:
        hm = dt.datetime.now(IST).hour * 100 + dt.datetime.now(IST).minute
        w["sent"] = True
        json.dump(w, open(p + ".tmp", "w")); os.replace(p + ".tmp", p)
        if S.get("night") and (hm >= 2330 or hm < 1800):
            send("event status %s" % dt.datetime.now(IST).strftime("%H:%M"), position_report("STATUS after a change"))
            return "sent"
    return "quiet"


def main():
    a = sys.argv[1:]
    if not a or a[0] not in list(REPORTS) + ["watch", "show"]:
        print(__doc__); return
    if a[0] == "watch":
        print(watch()); return
    if a[0] == "show":
        print(REPORTS[a[1]]()); return
    text = REPORTS[a[0]]()
    print(text)
    print("sent:", send("%s %s" % (a[0], dt.datetime.now(IST).strftime("%d-%b %H:%M")), text))


if __name__ == "__main__":
    main()
