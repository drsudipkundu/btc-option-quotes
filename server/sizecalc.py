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
    print(txt)
    if show:
        return
    json.dump({"up_ts": R["up_ts"], "step": R["step"], "ts": now}, open(ST_F, "w"))
    new = not os.path.exists(CSV_F)
    with open(CSV_F, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_ist", "equity_usd", "btc", "ladder_armed", "claim_usd", "spare_usd", "by_spare", "by_loss", "would_choose", "step_limited", "live_base"])
        w.writerow([dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"), "%.2f" % equity, "%.0f" % price, ",".join(armed), "%.0f" % R["claim"],
                    "%.0f" % R["spare"], "%.3f" % R["by_spare"], "%.3f" % R["by_loss"], R["size"], R["step"], base])
    try:
        import bot as B
        B.MODE = "LIVE"
        B.Notifier().send("NIGHT SIZE (paper): would choose %.2f BTC, live %.2f" % (R["size"], base), txt)
    except Exception as e:
        print("email failed:", e)


if __name__ == "__main__":
    main()
