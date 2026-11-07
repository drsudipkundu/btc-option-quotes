"""Night-sell size calculator, PHASE 1 (paper only) - 6-Nov-2026.
Reads the real serverbot balance (read-only), works out the night-sell size the plan formula WOULD choose, logs it
(logs/sizecalc.csv) and emails it. It NEVER places orders and NEVER changes the live size (state/night_live_cfg.json).
Formula (plan of 5-Nov):  spare = equity - ladder claim - crash buffer
  size = min( spare / (margin + crash-night loss per 0.01 BTC) , loss-budget size , hard cap 0.05 ), rounded DOWN to 0.01 BTC.
  Size down at once; size up at most +0.01 BTC per 7 days (shown as the 'step-limited' size).
All fixed numbers are ASSUMPTIONS in SETTINGS (edit state/sizecalc.json to change) - see the email text.
  venv/bin/python sizecalc.py          one calculation now (also what cron runs at 23:20 IST), emails + logs
  venv/bin/python sizecalc.py --show   same but no email, no log
"""
import os, sys, json, time, csv, datetime as dt

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CFG_F = os.path.join(HOME, "state", "sizecalc.json")
ST_F = os.path.join(HOME, "state", "sizecalc_state.json")
CSV_F = os.path.join(HOME, "logs", "sizecalc.csv")
ACCT = "serverbot"
SETTINGS = dict(
    usd_inr=88.0,              # rupees per dollar (only for showing rupees)
    ladder_claim_frac=0.715,   # ladder claim = brake BTC x price x this (Rs 13.6 L at 0.28 BTC brake, 2018-type; to verify)
    crash_buffer_frac=0.0,     # of equity kept untouched (plan figures: Rs 15 L - Rs 13.6 L claim = Rs 1.4 L spare, so 0 for now)
    margin_per_001_usd=4.5,    # initial margin for 0.01 BTC short option (observed 8.92 USD for 0.02)
    crash_loss_per_001_usd=357.0,  # -20 % crash night, unprotected: Rs 3.14 L per 0.1 BTC => 357 USD per 0.01 BTC
    loss_budget_inr=150000.0,  # worst-night loss budget (Sudip, 5-Nov: Rs 1.5 L at 0.04 base)
    hard_cap_btc=0.05,         # guard max_order_btc
    step_up_btc=0.01, step_days=7,
    fall=0.40,                 # Sudip 6-Nov: reserve for a 40 % BTC fall within 24 h
    ceiling_btc=0.06,          # Sudip 6-Nov: v4 ceiling 0.06 at Rs 20 L (final at this stage)
    ladder_gap=0.005, ladder_lot=0.004, ladder_cap_btc=0.28,  # safest case: smallest v13 gap, big lot
    v4_max_mult=3.0, strike_away=0.04,  # v4 can sell 3 x base; strike ~4 % away; crash guard assumed to FAIL
    # 7-Nov-2026 SAFE-BALANCE rule (Sudip agreed Rs 25,000 per 0.01 BTC base at BTC ~75.5k): money to keep free so the
    # night sale is never liquidated, crash guard WORKING (insurance caps the loss), recomputed nightly from price/ATR/HV14
    cg_mult=2.0, ins_beyond=0.04,       # crash guard: trigger 2 x ATR14 from entry, insurance 4 % beyond the trigger
    ins_cost_frac=0.005,                # insurance premium allowance, of notional sold
    margin_stress_frac=0.05,            # margin Delta may block in a crash, of notional (known rule 0.25-0.5 %; 10x room)
    time_value_frac=0.005,              # option time value at the guard trigger, of notional
    moved_hv=0.28347, k_sig=0.088192, normal_dist=0.025,  # v4 strike distance: moved night 1.4 x daily sigma, else 2.5 %
)


def settings():
    s = dict(SETTINGS)
    try:
        s.update({k: float(v) for k, v in json.load(open(CFG_F)).items() if k in s})
    except Exception:
        pass
    return s


def compute(equity, price, ladder_brake_btc, live_base, prev_up_ts, prev_step_size, now_ts, S=None):
    """Pure calculation. ladder_brake_btc = brake of a ladder armed in serverbot (0 if none)."""
    S = S or settings()
    claim = ladder_brake_btc * price * S["ladder_claim_frac"]
    buf = S["crash_buffer_frac"] * equity
    spare = equity - claim - buf
    per001 = S["margin_per_001_usd"] + S["crash_loss_per_001_usd"]
    by_spare = max(0.0, spare / per001 * 0.01)
    by_loss = S["loss_budget_inr"] / S["usd_inr"] / S["crash_loss_per_001_usd"] * 0.01
    raw = min(by_spare, by_loss, S["hard_cap_btc"])
    size = int(raw / 0.01 + 1e-9) / 100.0
    # step limit: down at once, up +step_up_btc at most once per step_days
    prev = prev_step_size if prev_step_size is not None else live_base
    if size <= prev:
        step, up_ts = size, prev_up_ts
    elif now_ts - (prev_up_ts or 0) >= S["step_days"] * 86400:
        step, up_ts = round(min(size, prev + S["step_up_btc"]), 2), now_ts
    else:
        step, up_ts = prev, prev_up_ts
    binding = "money left after the ladder claim" if by_spare <= min(by_loss, S["hard_cap_btc"]) else (
        "Rs %.1f L loss budget" % (S["loss_budget_inr"] / 1e5) if by_loss <= S["hard_cap_btc"] else "hard cap")
    return dict(equity=equity, price=price, claim=claim, buffer=buf, spare=spare, by_spare=by_spare, by_loss=by_loss,
                size=size, step=step, up_ts=up_ts, binding=binding)


HI = (1.0, 0.7354, 0.6032, 0.4709, 0.3386); MULT = (1, 1, 2 / 0.75, 4 / 0.75, 7 / 0.75)


def ladder_need(px, entry, held, S):
    """USD the ladder would spend buying lots if BTC fell S['fall'] from px in 24 h (zone gaps, stops at the cap)."""
    p, cost, h, floor = px, 0.0, held, px * (1 - S["fall"])
    while h + S["ladder_lot"] <= S["ladder_cap_btc"] + 1e-9:
        r = p / entry; z = 0
        for i in range(1, 5):
            if r < HI[i]:
                z = i
        p -= entry * S["ladder_gap"] * MULT[z]
        if p < floor:
            break
        cost += p * S["ladder_lot"]; h += S["ladder_lot"]
    return cost


def compute40(equity, price, held, tied, entry, S, ladder_on=True):
    """Sudip's final rule (6-Nov): free = equity - money tied in ladder lots; reserve = ladder buys on a 40 % fall;
    v4 base = min(ceiling, (free - reserve) / v4 loss on that 40 % night per 0.01 BTC base)."""
    need = ladder_need(price, entry or price, held, S) if ladder_on else 0.0
    loss001 = S["v4_max_mult"] * 0.01 * price * max(S["fall"] - S["strike_away"], 0)
    free = equity - tied
    raw = (free - need) / loss001 * 0.01
    size = int(max(0.0, min(raw, S["ceiling_btc"])) / 0.01 + 1e-9) / 100.0
    left = free - need - size / 0.01 * loss001
    return dict(need=need, loss001=loss001, free=free, raw=raw, size=size, left=left)


def safe_balance(price, ind, S):
    """USD to keep free per 0.01 BTC base (v4 at its max 3 x) so tonight's sale survives any crash with the guard working.
    cap = loss between the sold strike and the insurance strike (fixed once the guard fires) + insurance cost + stress margin."""
    hv14, atr = ind["hv14"], ind["atr"]
    moved = hv14 > S["moved_hv"]
    dist = hv14 * S["k_sig"] if moved else S["normal_dist"]
    trig = S["cg_mult"] * atr / price
    n = S["v4_max_mult"] * 0.01 * price                       # notional sold per 0.01 base at 3 x
    before = n * (max(0.0, trig - dist) + S["time_value_frac"])
    cap = n * max(0.0, (1 - dist) - (1 - S["ins_beyond"]) * (1 - trig))
    ins, mar = n * S["ins_cost_frac"], n * S["margin_stress_frac"]
    return dict(moved=moved, dist=dist, trig=trig, notional=n, before=before, cap=cap, ins=ins, margin=mar,
                safe=cap + ins + mar, hv14=hv14, atr=atr)


def tonight_ind():
    import delta_api as d
    from nightlogic import indicators
    now = time.time()
    r = d.public("/v2/history/candles", {"resolution": "1d", "symbol": "BTCUSD", "start": int(now - 400 * 86400), "end": int(now)})["result"]
    return indicators(sorted(r, key=lambda x: x["time"]), now)


def ladder_state(keys):
    """held BTC, money tied (USD, at buy prices if known) and cycle entry of the armed ladder in serverbot."""
    held = tied = 0.0; entry = None
    for k in keys:
        try:
            d = json.load(open(os.path.join(HOME, "state", "live_%s_state.json" % k)))["ladder"]
        except Exception:
            continue
        entry = d.get("entry") or entry
        for lot in d.get("lots", []):
            q = (lot.get("c") or lot.get("q") or 0) * 0.001 if isinstance(lot, dict) else 0
            p = (lot.get("price") or lot.get("p") or 0) if isinstance(lot, dict) else 0
            held += q; tied += q * p
    return held, tied, entry


def gather():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HOME, ".env"))
    import liveorders as LO, control
    cl = LO.Live(ACCT)
    bal = {b["asset"]: b for b in cl.balance()}
    equity = float(bal.get("USD", {}).get("bal", 0))
    price = float(cl.ticker("BTCUSD")["mark"])
    ll = {}
    try:
        ll = json.load(open(os.path.join(HOME, "state", "ladder_live_cfg.json")))
    except Exception:
        pass
    armed = [k for k, v in ll.items() if v.get("armed") and v.get("acct") == ACCT]
    brake = max([control.brake_for(k) for k in armed] or [0.0])
    try:
        base = float(json.load(open(os.path.join(HOME, "state", "night_live_cfg.json"))).get("base", 0))
    except Exception:
        base = 0.0
    return equity, price, brake, armed, base, control.brake_for("lv13")


def report(R, S, armed, base, brake_v13):
    inr = lambda u: "Rs %.2f L" % (u * S["usd_inr"] / 1e5)
    alt = compute(R["equity"], R["price"], brake_v13, base, 0, None, time.time(), S) if not armed else None
    L = ["Night-sell size calculator (PAPER, no orders). %s IST" % dt.datetime.now(IST).strftime("%d-%b %H:%M"),
         "Serverbot equity: %.0f USD (%s). BTC %.0f." % (R["equity"], inr(R["equity"]), R["price"]),
         "Ladder armed in serverbot: %s -> claim %.0f USD (%s)." % (", ".join(armed) or "none", R["claim"], inr(R["claim"])),
         "Crash buffer: %.0f USD. Spare: %.0f USD (%s)." % (R["buffer"], R["spare"], inr(R["spare"])),
         "Size allowed by spare money: %.3f BTC | by loss budget (Rs %.1f L): %.3f BTC | hard cap %.2f BTC." % (
             R["by_spare"], S["loss_budget_inr"] / 1e5, R["by_loss"], S["hard_cap_btc"]),
         "=> WOULD CHOOSE %.2f BTC (limited by %s). Step-limited (up +%.2f per %d days): %.2f BTC." % (
             R["size"], R["binding"], S["step_up_btc"], S["step_days"], R["step"]),
         "Live night size now: %.3f BTC (unchanged by this calculator)." % base]
    if alt:
        L.append("If v13 (brake %.2f BTC) were armed in serverbot today: would choose %.2f BTC (claim %.0f USD, spare %.0f USD)." % (
            brake_v13, alt["size"], alt["claim"], alt["spare"]))
    L.append("Assumptions (edit state/sizecalc.json): " + ", ".join("%s=%s" % (k, S[k]) for k in S))
    return "\n".join(L)


def main():
    show = "--show" in sys.argv
    S = settings()
    equity, price, brake, armed, base, brake_v13 = gather()
    try:
        st = json.load(open(ST_F))
    except Exception:
        st = {}
    now = time.time()
    R = compute(equity, price, brake, base, st.get("up_ts"), st.get("step"), now, S)
    txt = report(R, S, armed, base, brake_v13)
    held, tied, entry = ladder_state(armed)
    if armed and held and not tied:
        tied = held * price  # lot prices not readable: count held lots at market (1x)
    Q = compute40(equity, price, held, tied, entry, S, ladder_on=bool(armed))
    txt = ("FINAL RULE (Sudip 6-Nov, 40 %% fall reserve, ceiling %.2f): WOULD CHOOSE %.2f BTC\n"
           "  free %.0f USD (equity - %.0f tied in %.3f BTC of ladder lots) | ladder reserve for a %d %% fall %.0f USD | "
           "v4 loss on that night %.0f USD per 0.01 base (3x, guard fails) | money left after such a night %.0f USD (%s)\n"
           % (S["ceiling_btc"], Q["size"], Q["free"], tied, held, int(S["fall"] * 100), Q["need"], Q["loss001"], Q["left"],
              "Rs %.2f L" % (Q["left"] * S["usd_inr"] / 1e5)))
    if not armed:
        Q2 = compute40(equity, price, 0.0, 0.0, price, S)
        txt += "  If v13 started today (empty ladder): would choose %.2f BTC, ladder reserve %.0f USD, left %.0f USD\n" % (Q2["size"], Q2["need"], Q2["left"])
    try:
        ind = tonight_ind()
        B = safe_balance(price, ind, S)
        rs = lambda u: "Rs %s" % format(int(round(u * S["usd_inr"], -2)), ",")
        sb = int(max(0.0, min((Q["free"] - Q["need"]) / B["safe"] * 0.01, S["ceiling_btc"])) / 0.01 + 1e-9) / 100.0
        txt += ("SAFE-BALANCE RULE (7-Nov, crash guard working): keep %.0f USD (%s) free per 0.01 BTC base\n"
                "  tonight %s night: strike %.1f %% away, guard trigger %.1f %% (2 x ATR %.0f), 3 x = %.0f USD notional per 0.01 base\n"
                "  open loss before the hedge %.0f USD (%s) | capped loss with insurance %.0f USD (%s) | insurance %.0f | margin room %.0f USD\n"
                "  live base %.2f needs %.0f USD (%s); money free after the ladder reserve allows %.2f BTC base (ceiling %.2f)\n"
                % (B["safe"], rs(B["safe"]), "MOVED" if B["moved"] else "normal", B["dist"] * 100, B["trig"] * 100, B["atr"], B["notional"],
                   B["before"], rs(B["before"]), B["cap"], rs(B["cap"]), B["ins"], B["margin"],
                   base, B["safe"] * base / 0.01, rs(B["safe"] * base / 0.01), sb, S["ceiling_btc"]))
        R["safe001"], R["safe_size"] = B["safe"], sb
    except Exception as e:
        txt += "(safe-balance rule failed: %s)\n" % e
    txt += "\nOld plan formula (static claim, for comparison):\n" + report(R, S, armed, base, brake_v13)
    R["size"] = Q["size"]
    try:
        import marginwatch
        txt += "\n\n" + marginwatch.summary()
    except Exception as e:
        txt += "\n\n(margin watch failed: %s)" % e
    print(txt)
    if show:
        return
    json.dump({"up_ts": R["up_ts"], "step": R["step"], "ts": now}, open(ST_F, "w"))
    new = not os.path.exists(CSV_F)
    with open(CSV_F, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_ist", "equity_usd", "btc", "ladder_armed", "claim_usd", "spare_usd", "by_spare", "by_loss", "would_choose_40pct_rule", "step_limited_old", "live_base"])
        w.writerow([dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"), "%.2f" % equity, "%.0f" % price, ",".join(armed), "%.0f" % R["claim"],
                    "%.0f" % R["spare"], "%.3f" % R["by_spare"], "%.3f" % R["by_loss"], R["size"], R["step"], base])
    if R.get("safe001"):
        sf = os.path.join(HOME, "logs", "safebalance.csv")
        new = not os.path.exists(sf)
        with open(sf, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time_ist", "btc", "safe_usd_per_001_base", "safe_inr_per_001_base", "live_base", "safe_rule_size"])
            w.writerow([dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"), "%.0f" % price, "%.0f" % R["safe001"],
                        "%.0f" % (R["safe001"] * S["usd_inr"]), base, R["safe_size"]])
    try:
        import bot as B
        B.MODE = "LIVE"
        B.Notifier().send("NIGHT SIZE (paper, 40%% rule): would choose %.2f BTC, live %.2f" % (R["size"], base), txt)
    except Exception as e:
        print("email failed:", e)


if __name__ == "__main__":
    main()
