#!/usr/bin/env python3
"""sweep_report - REPORT ONLY daily balance check Ladderv9 <-> serverbot (built 23-Nov-2026, Sudip's spec).
Runs once a day at 18:15 IST (cron). It only sends GET requests. It NEVER moves money, places orders or changes anything.
It tells Sudip on Telegram what it WOULD move, so he can check the numbers for a few days before any live version exists.

What it works out (all in plain numbers, Rs lakh at Rs 85 per USD):
 1. Ladderv9 equity now (Delta: available + blocked margin).
 2. FALL test: BTC falls 40% from now. The v9 ladder keeps buying 0.002 BTC at each grid level below its last buy (last buy read from the
    LIFO of the account's own BTCUSD fills; if that does not match the position, it assumes the worst: every level below the price).
    Need = margin of everything held at the bottom (measured margin ratio of the live position) + the loss on the way down
    + margin of the call that may be short (open call, or the covered call still to be sold: after 17:50 the extra call can no longer
    be sold that day, so only the covered quantity is reserved).
 3. RISE test: BTC rises to the call's stop (strike x 1.06). Need = margin of ladder and call at that price + the call's intrinsic loss
    (ladder gains and premium ignored = conservative).
 4. Ladder needs the worse of the two, never less than the floor (Rs 10 L). Difference to equity = surplus or shortfall.
 5. Serverbot: equity, flat or not, spare above its floor (Rs 5 L).
 6. Decision as it WOULD be: move only if the difference is at least one step (0.01 night base = Rs 41,900), at most the daily cap
    (Rs 1 L at the start), never below the floors, only when serverbot is flat; if serverbot cannot cover a shortfall it only alerts.

Version 2 (24-Nov-2026, Sudip's agreed upgrade, STILL REPORT ONLY): the step is no longer a fixed Rs figure - it is the live safe balance per
0.01 base (sizecalc, moves with BTC). After the Ladderv9 <-> serverbot check it also reports the serverbot MULTIPLE check:
 7. Serverbot balance in steps (e.g. 16.7). A whole multiple plus a small cushion (default 4% of a step) keeps the base from being cut by a
    tiny BTC move. If the part above the whole number is >= 0.5 it reports a TOP-UP from the main-account pocket to the next multiple + cushion;
    if it is <= 0.4 (dead band 0.1 against flip-flop) the leftover above multiple + cushion goes BACK to the pocket; in between nothing moves.
 8. Pocket = main-account balance. Floor Rs 5,000 (nothing goes to serverbot below it), target about Rs 25,000 (leftovers refill it, never above).
    No move smaller than 0.1 step; daily cap and 'serverbot flat only' as before. Nothing here is hard-coded to a rupee step.
Only the pocket floor and pocket target are Sudip's own settings. THIS FILE CONTAINS NO TRANSFER CALL: it cannot move money.

  venv/bin/python sweep_report.py            run, log to logs/sweep_report.csv, Telegram message
  venv/bin/python sweep_report.py --show     run and only print (no Telegram, no log)
Settings can be changed in state/sweep_cfg.json (only the keys you list change). Server time is IST."""
import os, sys, csv, json, math, datetime as dt
import urllib.request, urllib.parse

H = os.path.expanduser(os.environ.get("BOT_HOME", "~/deltabot"))
sys.path.insert(0, H)
STATE = os.path.join(H, "state"); LOGS = os.path.join(H, "logs")
CPB = 1000.0                      # contracts per BTC for BTCUSD and BTC options

CFG = dict(
    fx=85.0, step_inr=41900.0, ladder_floor_inr=1_000_000.0, server_floor_inr=500_000.0, cap_inr=100_000.0,
    fall_pct=40.0, rise_stop_mult=1.06, buffer=1.0,
    lot_btc=0.002, brake_btc=0.28, call_ratio=0.38, fut_ratio_default=0.34,
    entry=84429.5, gap_pct=0.75, gap3_pct=2.0, gap4_pct=4.0, gap5_pct=7.0,
    z2_anchor=62076.5, z2_lo_pct=60.32, z3_lo_pct=47.09, z4_lo_pct=33.86,
    since="2026-10-21",
    cushion_frac=0.04, topup_frac=0.5, deadband=0.1, min_move_frac=0.1,
    pocket_floor_inr=5000.0, pocket_target_inr=30000.0,
    ladder_max_inr=880_000.0,   # ladder max capital (Sudip 25-Nov): most it can ever block with BTC down to 0; reference line only for now
    calls_on=True,   # set false in state/sweep_cfg.json once the v9 calls are stopped: no call margin, no rise test
)


def load_cfg():
    c = dict(CFG)
    try:
        c.update(json.load(open(os.path.join(STATE, "sweep_cfg.json"))))
    except Exception:
        pass
    return c


def f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def lakh(inr):
    return "%.2f L" % (inr / 100000.0)


def tg(text):
    c = {}
    try:
        for ln in open(os.path.join(STATE, "telegram.env")):
            if "=" in ln:
                k, v = ln.strip().split("=", 1); c[k] = v
    except OSError:
        pass
    tok, chat = c.get("TG_TOKEN"), c.get("TG_CHAT")
    if not tok or not chat:
        print("(telegram not configured)"); return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, data, timeout=15).read()
    except Exception as e:
        print("telegram send failed:", type(e).__name__)


# ------------------------------------------------------------------ serverbot multiple + main-account pocket (pure, testable)
def pocket_plan(eq_inr, step_inr, pocket_inr, c, s_flat=True, daily_left_inr=None):
    """eq_inr = serverbot balance (after any Ladderv9 sweep move), step_inr = live safe balance per 0.01 base in Rs.
    Returns dict(n, whole, frac, move_inr (+ pocket -> serverbot, - serverbot -> pocket), why, base_now, base_after)."""
    step = max(step_inr, 1.0)
    n = eq_inr / step
    whole = math.floor(n + 1e-9)
    frac = n - whole
    cush, hi = c["cushion_frac"], c["topup_frac"]
    lo = hi - c["deadband"]
    minmv = c["min_move_frac"] * step
    cap = c["cap_inr"] if daily_left_inr is None else daily_left_inr
    out = dict(n=n, whole=whole, frac=frac, move_inr=0.0, base_now=whole / 100.0, base_after=whole / 100.0, why="")
    avail = max(pocket_inr - c["pocket_floor_inr"], 0.0)
    if not s_flat:
        out["why"] = "serverbot is not flat: no pocket move today"
        return out
    if frac >= hi - 1e-9:                                   # TOP-UP to the next multiple + cushion
        need = (whole + 1 + cush) * step - eq_inr
        if need < minmv:
            out["why"] = "top-up needed Rs %.0f is below the minimum move (0.1 step)" % need
        elif need > cap:
            out["why"] = "top-up needed Rs %.0f is above the daily cap Rs %.0f: no move" % (need, cap)
        elif need > avail:
            out["why"] = "TOP-UP needed Rs %.0f but the pocket has only Rs %.0f above its floor (Rs %.0f): no move - add money to the main account" % (
                need, avail, c["pocket_floor_inr"])
        else:
            out["move_inr"] = need; out["base_after"] = (whole + 1) / 100.0
            out["why"] = "fraction %.2f >= %.2f: top up Rs %.0f from the pocket to reach %d steps + cushion" % (frac, hi, need, whole + 1)
    elif frac <= lo + 1e-9:                                 # PULL BACK the leftover above multiple + cushion
        left = eq_inr - (whole + cush) * step
        room = max(c["pocket_target_inr"] - pocket_inr, 0.0)
        mv = min(left, room, cap)
        if left < minmv:
            out["why"] = "fraction %.2f: leftover above multiple + cushion Rs %.0f is below the minimum move" % (frac, max(left, 0))
        elif room < minmv:
            out["why"] = "fraction %.2f: leftover Rs %.0f stays in serverbot (pocket already at its target Rs %.0f)" % (frac, left, c["pocket_target_inr"])
        else:
            out["move_inr"] = -mv
            out["why"] = "fraction %.2f <= %.2f: leftover Rs %.0f above %d steps + cushion goes back to the pocket (Rs %.0f)" % (frac, lo, left, whole, mv)
    else:
        out["why"] = "fraction %.2f is inside the dead band (%.2f to %.2f): no move" % (frac, lo, hi)
    if not out["move_inr"] and 0 <= frac < cush and not out["why"].startswith("serverbot"):
        out["why"] += "; note: only %.0f%% of a step above %d steps - a small BTC rise could cut the base by 0.01" % (frac * 100, whole)
    return out


# ------------------------------------------------------------------ grid of ladder buy levels (v9 spec)
def grid_levels(c):
    E = c["entry"]; step = E * c["gap_pct"] / 100.0
    lv = []
    p = c["z2_anchor"]; lo2 = E * c["z2_lo_pct"] / 100.0
    while p >= lo2:
        lv.append(p); p -= step
    g3 = E * c["gap3_pct"] / 100.0; lo3 = E * c["z3_lo_pct"] / 100.0
    while p >= lo3:
        lv.append(p); p -= g3
    g4 = E * c["gap4_pct"] / 100.0; lo4 = E * c["z4_lo_pct"] / 100.0
    while p >= lo4:
        lv.append(p); p -= g4
    g5 = E * c["gap5_pct"] / 100.0
    while p > 1000:
        lv.append(p); p -= g5
    return lv


# ------------------------------------------------------------------ last buy from the account's own fills (LIFO)
def lifo_last_buy(cl, pid, since, held_contracts):
    """Returns (last_buy_price or None, note). Walks the BTCUSD fills oldest to newest: buy pushes, sell pops from the top."""
    rows, params, pages = [], {"product_ids": pid, "page_size": 100}, 0
    while True:
        res = cl._p("GET", "/v2/fills", params)
        got = res.get("result") or []
        rows += got
        after = (res.get("meta") or {}).get("after"); pages += 1
        old = got and min(str(x.get("created_at", "9")) for x in got) < since
        if not got or not after or old or pages > 60:
            break
        params["after"] = after
    rows = [x for x in rows if str(x.get("created_at", "")) >= since]
    rows.sort(key=lambda x: str(x.get("created_at", "")))
    stack = []
    for x in rows:
        sz = int(round(f(x.get("size")))); px = f(x.get("price"))
        if str(x.get("side")) == "buy":
            stack.append([sz, px])
        else:
            while sz > 0 and stack:
                take = min(sz, stack[-1][0]); stack[-1][0] -= take; sz -= take
                if stack[-1][0] == 0:
                    stack.pop()
    tot = sum(s for s, _ in stack)
    if stack and abs(tot - held_contracts) <= 1:
        return min(p for _, p in stack), "last buy %.1f from fills (LIFO matches position %d contracts)" % (min(p for _, p in stack), held_contracts)
    return None, "fills LIFO (%d contracts) does not match position (%d) -> worst case used" % (tot, held_contracts)


# ------------------------------------------------------------------ account reading
def read_acct(Live, name):
    cl = Live(name)
    bal = cl._p("GET", "/v2/wallet/balances")["result"] or []
    rows = [b for b in bal if f(b.get("balance")) > 0 or f(b.get("blocked_margin")) > 0]
    b0 = rows[0] if rows else {}
    pos = [p for p in (cl._p("GET", "/v2/positions/margined")["result"] or []) if f(p.get("size"))]
    orders = cl._p("GET", "/v2/orders", {"states": "open,pending"}).get("result") or []
    eq = f(b0.get("available_balance")) + f(b0.get("blocked_margin"))
    return cl, dict(equity_usd=eq, avail=f(b0.get("available_balance")), blocked=f(b0.get("blocked_margin")), pos=pos, orders=orders)


def parse_strike(sym):
    try:
        return float(sym.split("-")[2])
    except Exception:
        return 0.0


# ------------------------------------------------------------------ main calculation
def compute(c, Live, Pub):  # tk below is the public BTCUSD ticker
    c = dict(c)
    pub = Pub()
    tk = pub._http("GET", "/v2/tickers/BTCUSD")["result"]
    spot = f(tk.get("spot_price")) or f(tk.get("mark_price"))
    lcl, L = read_acct(Live, "ladder9")
    scl, S = read_acct(Live, "serverbot")

    fut = [p for p in L["pos"] if str(p.get("product_symbol")) == "BTCUSD"]
    H0 = sum(f(p.get("size")) for p in fut) / CPB
    fut_margin = sum(f(p.get("margin")) for p in fut)
    r_fut = fut_margin / (H0 * spot) if H0 > 0 and spot > 0 and fut_margin > 0 else c["fut_ratio_default"]
    calls = [p for p in L["pos"] if str(p.get("product_symbol", "")).startswith("C-") and f(p.get("size")) < 0]
    call_btc = sum(abs(f(p.get("size"))) for p in calls) / CPB
    K = max([parse_strike(p["product_symbol"]) for p in calls] or [0.0])
    call_note = "open call %.3f BTC, strike %.0f" % (call_btc, K) if calls else "no call open; covered call (up to the held BTC) reserved"
    if not c.get("calls_on", True):
        call_note = "CALLS OFF (no call margin reserved, no rise test)" + ("; WARNING open call %.3f BTC still found" % call_btc if calls else "")
        if not calls:
            call_btc, K = 0.0, 0.0
    elif not calls:
        call_btc, K = H0, spot * 1.05

    # last buy
    last_buy, lb_note = None, "no ladder position"
    if H0 > 0:
        try:
            pid = int(tk.get("product_id"))
            last_buy, lb_note = lifo_last_buy(lcl, pid, c["since"], int(round(H0 * CPB)))
        except Exception as e:
            lb_note = "fills not read (%s) -> worst case used" % type(e).__name__
    if last_buy is None:
        last_buy = spot * 1.0001

    # FALL test
    Pst = spot * (1 - c["fall_pct"] / 100.0)
    hold = H0; loss = H0 * (spot - Pst); nlots = 0
    for lvl in grid_levels(c):
        if lvl >= last_buy or lvl < Pst:
            continue
        if hold + c["lot_btc"] > c["brake_btc"] + 1e-9:
            break
        hold += c["lot_btc"]; loss += c["lot_btc"] * (lvl - Pst); nlots += 1
    margin_fall = r_fut * hold * Pst + c["call_ratio"] * call_btc * Pst
    need_fall = margin_fall + loss

    # reference: BTC down to about 0 (ladder buys every remaining level up to the brake)
    P0 = max(spot * 0.001, 1.0)
    hold0 = H0; loss0 = H0 * (spot - P0)
    for lvl in grid_levels(c):
        if lvl >= last_buy or lvl < P0:
            continue
        if hold0 + c["lot_btc"] > c["brake_btc"] + 1e-9:
            break
        hold0 += c["lot_btc"]; loss0 += c["lot_btc"] * (lvl - P0)
    need_zero = r_fut * hold0 * P0 + c["call_ratio"] * call_btc * P0 + loss0

    # RISE test
    if K > 0:
        Pup = K * c["rise_stop_mult"]
        loss_up = call_btc * max(0.0, Pup - K)
        margin_up = r_fut * H0 * Pup + c["call_ratio"] * call_btc * Pup
        need_rise = margin_up + loss_up
    else:   # calls off: nothing short above the market, ladder only gains on a rise
        Pup = spot; need_rise = 0.0

    need_usd = max(need_fall, need_rise) * c["buffer"]
    need_inr = max(need_usd * c["fx"], c["ladder_floor_inr"])
    eq_inr = L["equity_usd"] * c["fx"]
    diff = eq_inr - need_inr

    s_eq = S["equity_usd"] * c["fx"]
    s_flat = not S["pos"] and not S["orders"]
    s_spare = s_eq - c["server_floor_inr"]

    step_src = "fixed setting"
    try:                                                    # the step follows BTC: live safe balance per 0.01 base (sizecalc)
        import sizecalc as SC
        safe_usd = SC.safe_balance(spot, SC.tonight_ind(), SC.settings())["safe"]
        c["step_inr"] = safe_usd * c["fx"]; step_src = "live safe balance per 0.01 (moves with BTC)"
    except Exception as e:
        step_src = "fixed setting (live safe balance not read: %s)" % type(e).__name__
    step, cap = c["step_inr"], c["cap_inr"]
    move, why = 0.0, ""
    if diff >= step:
        mv = min(math.floor(diff / step) * step, cap)
        if mv < step:
            why = "surplus but the cap is below one step"
        elif not s_flat:
            why = "surplus Rs %s but serverbot is not flat" % lakh(diff)
        else:
            move = mv; why = "surplus %s -> move to serverbot" % lakh(diff)
    elif diff <= -step:
        need_in = math.ceil(-diff / step) * step
        if not s_flat:
            why = "SHORTFALL %s but serverbot is not flat: alert only" % lakh(-diff)
        elif s_spare < need_in:
            why = "SHORTFALL %s and serverbot spare above its floor is only %s: ALERT, nothing moved" % (lakh(-diff), lakh(max(s_spare, 0)))
        else:
            move = -min(need_in, cap)
            why = "shortfall %s -> move from serverbot to Ladderv9" % lakh(-diff)
            if need_in > cap:
                why += " (cap %s, still short %s tomorrow)" % (lakh(cap), lakh(need_in - cap))
    else:
        why = "difference %s is below one step (%s): no move" % (lakh(diff), lakh(step))

    # ---- serverbot multiple + main-account pocket (report only)
    pocket_inr, pocket_err = None, ""
    try:
        mcl = Live("main")
        row = [b for b in (mcl._p("GET", "/v2/wallet/balances")["result"] or []) if b.get("asset_symbol") == "USD"]
        pocket_inr = f(row[0].get("balance")) * c["fx"] if row else 0.0
    except Exception as e:
        pocket_err = type(e).__name__
    eq_after = s_eq + move                                   # serverbot balance after the Ladderv9 sweep move above (if it were made)
    if pocket_inr is None:
        pk = dict(n=eq_after / step, whole=math.floor(eq_after / step), frac=0, move_inr=0.0, base_now=0, base_after=0,
                  why="main-account balance not readable (%s): pocket not checked" % pocket_err)
    else:
        pk = pocket_plan(eq_after, step, pocket_inr, c, s_flat, None)   # pocket moves are the main account's own money: own cap, not shared with the Ladderv9 sweep
    d = dict(c=c, step_src=step_src, pocket_inr=pocket_inr, eq_after=eq_after, pk=pk, spot=spot, H0=H0, r_fut=r_fut, last_buy=last_buy, lb_note=lb_note, call_note=call_note, Pst=Pst, nlots=nlots,
             hold_stress=hold, need_zero_inr=need_zero * c["fx"], hold_zero=hold0, need_fall_inr=need_fall * c["fx"], Pup=Pup, need_rise_inr=need_rise * c["fx"], need_inr=need_inr,
             eq_inr=eq_inr, diff=diff, s_eq=s_eq, s_flat=s_flat, s_spare=s_spare, move=move, why=why)
    return d


def pocket_lines(d):
    c, pk = d["c"], d["pk"]
    pm = pk["move_inr"]
    ptxt = "nothing" if not pm else ("Rs %.0f from the main-account pocket to serverbot" % pm if pm > 0 else "Rs %.0f from serverbot back to the pocket" % -pm)
    need_worst = (1 + c["cushion_frac"] - c["topup_frac"]) * c["step_inr"]
    pocket = "not read" if d["pocket_inr"] is None else "Rs %.0f" % d["pocket_inr"]
    return ["SERVERBOT MULTIPLE: balance %s after the sweep = %.2f steps of Rs %.0f (step %s). Base it allows now %.2f." % (
                lakh(d["eq_after"]), pk["n"], c["step_inr"], d["step_src"], pk["base_now"]),
            "POCKET (main account) %s, floor Rs %.0f, target Rs %.0f." % (pocket, c["pocket_floor_inr"], c["pocket_target_inr"]),
            "POCKET WOULD MOVE: %s -> base would be %.2f. Reason: %s." % (ptxt, pk["base_after"], pk["why"])] + (
            ["WARNING: the worst top-up (balance just at %.1f steps) needs Rs %.0f, so the pocket target should be at least Rs %.0f (now Rs %.0f)." % (
                c["topup_frac"], need_worst, c["pocket_floor_inr"] + need_worst, c["pocket_target_inr"])] if need_worst > c["pocket_target_inr"] - c["pocket_floor_inr"] else [])


def message(c, d):
    mv = d["move"]
    mtxt = "nothing" if not mv else ("Rs %s from Ladderv9 to serverbot" % lakh(mv) if mv > 0 else "Rs %s from serverbot to Ladderv9" % lakh(-mv))
    return "\n".join([
        "SWEEP REPORT (report only - nothing was moved) %s IST" % dt.datetime.now().strftime("%d-%b %H:%M"),
        "BTC %.0f. Ladderv9 holds %.3f BTC (margin ratio %.2f). %s." % (d["spot"], d["H0"], d["r_fut"], d["call_note"]),
        "Ladderv9 equity %s. Serverbot equity %s (%s)." % (lakh(d["eq_inr"]), lakh(d["s_eq"]), "flat" if d["s_flat"] else "NOT flat"),
        "FALL %d%% to %.0f: ladder holds %.3f BTC (+%d lots), needs %s." % (c["fall_pct"], d["Pst"], d["hold_stress"], d["nlots"], lakh(d["need_fall_inr"])),
        "RISE to call stop %.0f: needs %s." % (d["Pup"], lakh(d["need_rise_inr"])),
        "BTC to 0: ladder would hold %.3f BTC and needs %s. Ladder max capital %s (%s)." % (d["hold_zero"], lakh(d["need_zero_inr"]), lakh(c["ladder_max_inr"]),
            "enough" if d["need_zero_inr"] <= c["ladder_max_inr"] else "ALERT: BTC-to-0 need is above the max"),
        "Ladder requirement (worse of both, floor %s): %s. Difference: %s." % (lakh(c["ladder_floor_inr"]), lakh(d["need_inr"]), ("+" if d["diff"] >= 0 else "-") + lakh(abs(d["diff"]))),
        "WOULD MOVE: %s. Reason: %s." % (mtxt, d["why"]),
        "Basis: %s." % d["lb_note"],
    ] + pocket_lines(d))


def detail(c, d):
    """Long version for the e-mail: every number and setting, so the whole picture is readable without a PC."""
    L = [message(c, d), "", "---- DETAILS ----",
         "Settings used: fx Rs %.0f per USD; step Rs %.0f; floors Ladderv9 %s, serverbot %s; daily cap %s; fall %.0f%%; rise stop = strike x %.2f." % (
             c["fx"], c["step_inr"], lakh(c["ladder_floor_inr"]), lakh(c["server_floor_inr"]), lakh(c["cap_inr"]), c["fall_pct"], c["rise_stop_mult"]),
         "Fall test: price %.0f -> %.0f. Held now %.4f BTC, held at the bottom %.4f BTC (%d extra lots of %.3f BTC, brake %.2f BTC)." % (
             d["spot"], d["Pst"], d["H0"], d["hold_stress"], d["nlots"], c["lot_btc"], c["brake_btc"]),
         "Fall test need %s = margin (ladder ratio %.2f, call ratio %.2f) + loss on the way down." % (lakh(d["need_fall_inr"]), d["r_fut"], c["call_ratio"]),
         "Rise test need %s at price %.0f (ladder and call margin + call loss; ladder gain and premium ignored)." % (lakh(d["need_rise_inr"]), d["Pup"]),
         "Serverbot: equity %s, spare above floor %s, %s." % (lakh(d["s_eq"]), lakh(max(d["s_spare"], 0)), "flat" if d["s_flat"] else "not flat"),
         "Last buy / call basis: %s; %s." % (d["lb_note"], d["call_note"]),
         "Multiple rules: cushion %.0f%% of a step; top up when the part above the whole number is >= %.2f; pull back when <= %.2f (dead band %.2f); minimum move %.2f step; pocket floor Rs %.0f, target Rs %.0f." % (
             c["cushion_frac"] * 100, c["topup_frac"], c["topup_frac"] - c["deadband"], c["deadband"], c["min_move_frac"], c["pocket_floor_inr"], c["pocket_target_inr"]),
         "REPORT ONLY: no money was moved and no order was placed."]
    return "\n".join(L)


def email(subject, body):
    try:
        import bot
        bot.Notifier()._send_now(subject, body)
        return True
    except Exception as e:
        print("email failed:", type(e).__name__, str(e)[:100])
        return False


def bot_off(name):
    """26-Nov-2026: Telegram /stop <bot> sets a flag in state/bots_off.json; the scheduled run then does nothing until /go <bot>"""
    try:
        return bool(json.load(open(os.path.join(STATE, "bots_off.json"))).get(name))
    except Exception:
        return False


def main():
    show = "--show" in sys.argv
    if not show and bot_off("sweep"):
        print("sweep bot is STOPPED by you (Telegram /go sweep starts it again)"); return
    c = load_cfg()
    from liveorders import Live, Pub
    try:
        d = compute(c, Live, Pub)
    except Exception as e:
        t = "SWEEP REPORT failed: %s: %s. Nothing moved." % (type(e).__name__, str(e)[:200])
        print(t)
        if not show:
            tg(t); email("[DeltaBot] Sweep report FAILED", t)
        return
    c = d["c"]
    msg = message(c, d)
    print(msg)
    if show:
        return
    os.makedirs(LOGS, exist_ok=True)
    p = os.path.join(LOGS, "sweep_report2.csv"); new = not os.path.exists(p)
    with open(p, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["time_ist", "spot", "held_btc", "ladder_eq_inr", "need_fall_inr", "need_rise_inr", "need_inr", "diff_inr", "server_eq_inr", "would_move_inr", "why",
                        "step_inr", "steps", "pocket_inr", "pocket_would_move_inr", "pocket_why"])
        w.writerow([dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), round(d["spot"], 1), round(d["H0"], 4), round(d["eq_inr"]),
                    round(d["need_fall_inr"]), round(d["need_rise_inr"]), round(d["need_inr"]), round(d["diff"]), round(d["s_eq"]), round(d["move"]), d["why"],
                    round(c["step_inr"]), round(d["pk"]["n"], 3), "" if d["pocket_inr"] is None else round(d["pocket_inr"]),
                    round(d["pk"]["move_inr"]), d["pk"]["why"]])
    tg(msg)
    email("[DeltaBot] Sweep report %s" % dt.datetime.now().strftime("%d-%b"), detail(c, d))


if __name__ == "__main__":
    main()
