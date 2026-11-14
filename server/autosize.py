"""Night-sell AUTO SIZE CUT (11-Nov-2026, Sudip: "build automatic size cutting, active").
Runs by cron at 23:22 IST, a few minutes before the 23:30 sale. It NEVER places an order.
Rule: night base allowed = balance / safe balance per 0.01 BTC (Rs 30,000 floor since 14-Nov-2026, from sizecalc), rounded DOWN to 0.01,
      never above Sudip's own base (the "max base" = the base he armed by hand).
  - allowed < live base  -> lower the base at once (state/night_live_cfg.json) and restart nightlive (only when flat).
  - allowed < 0.01       -> pause tonight's sale (disarm); re-armed by this script when the balance is enough again.
  - balance is back      -> raise +0.01 BTC at most once per 7 days, up to the max base.
  - anything unreadable  -> change nothing, Telegram note.   If the restart fails -> disarm (no sale tonight) + alert.
A base armed by hand (different from what this script last set) becomes the new max base.
  venv/bin/python autosize.py           run now (what cron runs)
  venv/bin/python autosize.py --show    only print what it would do, change nothing
  venv/bin/python autosize.py --off / --on    switch the auto cut off / on
"""
import os, sys, json, time, subprocess, datetime as dt

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CFG_F = os.path.join(HOME, "state", "night_live_cfg.json")
ST_F = os.path.join(HOME, "state", "autosize.json")
CSV_F = os.path.join(HOME, "logs", "autosize.csv")
STEP_UP, STEP_DAYS = 0.01, 7


def jload(p, d=None):
    try:
        return json.load(open(p))
    except Exception:
        return {} if d is None else d


def jsave(p, v):
    json.dump(v, open(p + ".tmp", "w"))
    os.replace(p + ".tmp", p)


def floor001(x):
    return int(max(0.0, x) / 0.01 + 1e-9) / 100.0


def decide(balance_usd, safe_usd_per_001, live_base, armed, st, now_ts):
    """Pure decision. Returns dict(action, base, max_base, allowed, note). action: none | cut | pause | raise | resume"""
    st = dict(st)
    max_base = st.get("max_base")
    if max_base is None or (armed and abs(live_base - st.get("last_set", live_base)) > 1e-9):
        max_base = live_base                      # first run, or Sudip armed a new base by hand
    allowed = min(floor001(balance_usd / safe_usd_per_001 * 0.01), max_base)
    paused = bool(st.get("auto_paused")) and not armed   # armed again by hand = the pause is over
    last_change = st.get("last_change_ts", 0)
    out = dict(action="none", base=live_base, max_base=max_base, allowed=allowed)
    if not armed and not paused:
        out["note"] = "night sell is disarmed by hand - nothing to do"
        return out
    if paused:                                    # this script paused the sale earlier
        if allowed >= 0.01:
            out.update(action="resume", base=min(allowed, 0.01 if max_base >= 0.01 else max_base))
        return out
    if allowed < 0.01:
        out.update(action="pause", base=live_base)
    elif allowed < live_base - 1e-9:
        out.update(action="cut", base=allowed)
    elif live_base < max_base - 1e-9 and allowed > live_base + 1e-9 and now_ts - last_change >= STEP_DAYS * 86400:
        out.update(action="raise", base=round(min(allowed, live_base + STEP_UP), 2))
    return out


def read_all():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HOME, ".env"))
    import nightwatch as NW, sizecalc as SC
    pos, b0, spot = NW.read_account()                       # GET requests only
    wallet = NW.f(b0.get("balance"))
    open_pos = [p for p in pos if abs(NW.f(p.get("size"))) > 0]
    S = SC.settings()
    safe = S["safe_floor_inr"] / S["usd_inr"]
    try:
        safe = SC.safe_balance(spot, SC.tonight_ind(), S)["safe"]
    except Exception as e:
        print("safe-balance calc failed, using the floor:", e)
    return wallet, spot, open_pos, safe, S["usd_inr"], NW.tg_send


def restart_ok():
    r = subprocess.run("sudo -n systemctl restart nightlive && sleep 4 && systemctl is-active nightlive", shell=True,
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip().endswith("active")


def main():
    show = "--show" in sys.argv
    st = jload(ST_F)
    if "--off" in sys.argv or "--on" in sys.argv:
        st["on"] = "--on" in sys.argv
        jsave(ST_F, st); print("auto size cut is", "ON" if st["on"] else "OFF"); return
    if not st.get("on", True) and not show:
        print("auto size cut is OFF"); return
    now = time.time()
    stamp = dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    cfg = jload(CFG_F)
    live_base, armed = float(cfg.get("base", 0)), bool(cfg.get("armed"))
    try:
        wallet, spot, open_pos, safe, fx, tg = read_all()
    except Exception as e:
        print(stamp, "could not read the account, nothing changed:", type(e).__name__, e)
        if not show:
            try:
                import nightwatch as NW
                NW.tg_send("AUTO SIZE: could not read the night account at %s. Nothing changed; tonight's base stays %.2f BTC." % (stamp, live_base))
            except Exception:
                pass
        return
    rs = lambda u: "Rs %s" % format(int(round(u * fx, -2)), ",")
    D = decide(wallet, safe, live_base, armed, st, now)
    line = "balance %s, needs %s per 0.01 BTC -> allowed %.2f BTC (max base %.2f, live base %.2f, armed %s)" % (
        rs(wallet), rs(safe), D["allowed"], D["max_base"], live_base, armed)
    print(stamp, "action:", D["action"], "|", line, "|", D.get("note", ""))
    if show:
        return
    msg = None
    if D["action"] != "none" and open_pos:
        D["action"] = "none"
        msg = "AUTO SIZE: a position is still open at %s, so the size was NOT changed. %s" % (stamp, line)
    elif D["action"] in ("cut", "raise", "resume"):
        new = dict(cfg); new["base"] = D["base"]; new["armed"] = True
        jsave(CFG_F, new)
        if restart_ok():
            st.update(last_set=D["base"], last_change_ts=now, auto_paused=False)
            word = {"cut": "CUT", "raise": "RAISED", "resume": "RESUMED"}[D["action"]]
            msg = "AUTO SIZE %s: tonight's night base is %.2f BTC (was %.2f). %s" % (word, D["base"], live_base, line)
        else:
            new["armed"] = False; jsave(CFG_F, new)
            st.update(last_set=D["base"], last_change_ts=now, auto_paused=True)
            msg = "AUTO SIZE PROBLEM: the bot could not be restarted with the new base %.2f, so tonight's sale is SWITCHED OFF (safe). %s" % (D["base"], line)
    elif D["action"] == "pause":
        new = dict(cfg); new["armed"] = False
        jsave(CFG_F, new)                         # nightlive reads 'armed' every tick: no restart needed
        st.update(auto_paused=True, last_change_ts=now)
        msg = "AUTO SIZE PAUSE: balance is too small for even 0.01 BTC, so tonight's sale is SWITCHED OFF. %s" % line
    else:
        st.setdefault("last_set", live_base)
    st["max_base"] = D["max_base"]; st["ts"] = now; st.setdefault("on", True)
    jsave(ST_F, st)
    new_f = not os.path.exists(CSV_F)
    with open(CSV_F, "a") as f:
        if new_f:
            f.write("time_ist,balance_usd,safe_usd_per_001,allowed,max_base,base_before,action,base_after\n")
        f.write("%s,%.2f,%.1f,%.2f,%.2f,%.3f,%s,%.3f\n" % (stamp, wallet, safe, D["allowed"], D["max_base"], live_base, D["action"],
                                                          jload(CFG_F).get("base", live_base)))
    if msg:
        tg(msg)


if __name__ == "__main__":
    main()
