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
    if not calls:
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

    # RISE test
    Pup = K * c["rise_stop_mult"]
    loss_up = call_btc * max(0.0, Pup - K)
    margin_up = r_fut * H0 * Pup + c["call_ratio"] * call_btc * Pup
    need_rise = margin_up + loss_up

    need_usd = max(need_fall, need_rise) * c["buffer"]
    need_inr = max(need_usd * c["fx"], c["ladder_floor_inr"])
    eq_inr = L["equity_usd"] * c["fx"]
    diff = eq_inr - need_inr

    s_eq = S["equity_usd"] * c["fx"]
    s_flat = not S["pos"] and not S["orders"]
    s_spare = s_eq - c["server_floor_inr"]

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

    d = dict(spot=spot, H0=H0, r_fut=r_fut, last_buy=last_buy, lb_note=lb_note, call_note=call_note, Pst=Pst, nlots=nlots,
             hold_stress=hold, need_fall_inr=need_fall * c["fx"], Pup=Pup, need_rise_inr=need_rise * c["fx"], need_inr=need_inr,
             eq_inr=eq_inr, diff=diff, s_eq=s_eq, s_flat=s_flat, s_spare=s_spare, move=move, why=why)
    return d


def message(c, d):
    mv = d["move"]
    mtxt = "nothing" if not mv else ("Rs %s from Ladderv9 to serverbot" % lakh(mv) if mv > 0 else "Rs %s from serverbot to Ladderv9" % lakh(-mv))
    return "\n".join([
        "SWEEP REPORT (report only - nothing was moved) %s IST" % dt.datetime.now().strftime("%d-%b %H:%M"),
        "BTC %.0f. Ladderv9 holds %.3f BTC (margin ratio %.2f). %s." % (d["spot"], d["H0"], d["r_fut"], d["call_note"]),
        "Ladderv9 equity %s. Serverbot equity %s (%s)." % (lakh(d["eq_inr"]), lakh(d["s_eq"]), "flat" if d["s_flat"] else "NOT flat"),
        "FALL %d%% to %.0f: ladder holds %.3f BTC (+%d lots), needs %s." % (c["fall_pct"], d["Pst"], d["hold_stress"], d["nlots"], lakh(d["need_fall_inr"])),
        "RISE to call stop %.0f: needs %s." % (d["Pup"], lakh(d["need_rise_inr"])),
        "Ladder requirement (worse of both, floor %s): %s. Difference: %s." % (lakh(c["ladder_floor_inr"]), lakh(d["need_inr"]), ("+" if d["diff"] >= 0 else "-") + lakh(abs(d["diff"]))),
        "WOULD MOVE: %s. Reason: %s." % (mtxt, d["why"]),
        "Basis: %s." % d["lb_note"],
    ])


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


def main():
    show = "--show" in sys.argv
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
    msg = message(c, d)
    print(msg)
    if show:
        return
    os.makedirs(LOGS, exist_ok=True)
    p = os.path.join(LOGS, "sweep_report.csv"); new = not os.path.exists(p)
    with open(p, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["time_ist", "spot", "held_btc", "ladder_eq_inr", "need_fall_inr", "need_rise_inr", "need_inr", "diff_inr", "server_eq_inr", "would_move_inr", "why"])
        w.writerow([dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), round(d["spot"], 1), round(d["H0"], 4), round(d["eq_inr"]),
                    round(d["need_fall_inr"]), round(d["need_rise_inr"]), round(d["need_inr"]), round(d["diff"]), round(d["s_eq"]), round(d["move"]), d["why"]])
    tg(msg)
    email("[DeltaBot] Sweep report %s" % dt.datetime.now().strftime("%d-%b"), detail(c, d))


if __name__ == "__main__":
    main()
