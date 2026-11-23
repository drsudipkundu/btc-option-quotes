"""One-off TRANSFER TEST (23-Nov-2026): can the server move money between Delta sub-accounts on its own?
Moves Rs 5,000 (USD 58.82 at Rs 85) serverbot -> ladder9, waits 30 minutes, moves it back, tells Sudip on Telegram.
Uses the MAIN account key (Delta allows sub-account transfers only with the parent account's key).
Never places an order. Never touches a trading bot. Never prints keys.

  python3 transfer_test.py check              read-only: user ids, balances, is serverbot flat (nothing moves)
  python3 transfer_test.py run --yes-move     check, move out, verify, wait 30 min, move back, verify, report
  python3 transfer_test.py back --yes-move    only the return leg (if the first run was interrupted)
  python3 transfer_test.py status             shows the state file

Safety rules built in:
- the amount is fixed here (USD 58.82); there is no amount argument
- refuses to run between 22:30 and 23:50 IST (night base check 23:22 and the 23:30 sale)
- refuses if serverbot has any open position or open order, or has less than USD 150 available
- every transfer is verified from the wallet balances; a transfer is never repeated automatically
- if the return leg fails, it says so loudly on Telegram and stops (state file keeps the facts)
"""
import os, sys, json, time, csv, datetime as dt
import urllib.request, urllib.parse

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
STATE = os.path.join(HOME, "state"); LOGS = os.path.join(HOME, "logs")
STF = os.path.join(STATE, "transfer_test.json")
CSVF = os.path.join(LOGS, "transfer_test.csv")
AMOUNT = "58.82"                 # USD, = Rs 5,000 at Rs 85
WAIT_S = 30 * 60
SRC, DST = "serverbot", "ladder9"
PATH = "/v2/wallets/sub_account_balance_transfer"


def tg(text):
    c = {}
    try:
        for ln in open(os.path.join(STATE, "telegram.env")):
            if "=" in ln:
                k, v = ln.strip().split("=", 1); c[k] = v
    except OSError:
        pass
    tok, chat = c.get("TG_TOKEN"), c.get("TG_CHAT")
    print(text)
    if not tok or not chat:
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, data, timeout=15).read()
    except Exception as e:
        print("telegram send failed:", type(e).__name__)


def now_ist():
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)


def log_row(*cols):
    os.makedirs(LOGS, exist_ok=True)
    new = not os.path.exists(CSVF)
    with open(CSVF, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_ist", "step", "detail", "result"])
        w.writerow([now_ist().strftime("%Y-%m-%d %H:%M:%S")] + list(cols))


def load_state():
    try:
        return json.load(open(STF))
    except Exception:
        return {}


def save_state(s):
    os.makedirs(STATE, exist_ok=True)
    tmp = STF + ".tmp"; json.dump(s, open(tmp, "w"), indent=1); os.replace(tmp, STF)


def clients():
    import liveorders as LO
    return {a: LO.Live(a) for a in ("main", SRC, DST)}


def user_id(cl):
    r = cl._p("GET", "/v2/profile")
    res = r.get("result") or {}
    uid = res.get("id") or res.get("user_id")
    if not uid:
        raise RuntimeError("profile has no user id")
    return str(uid)


def usd(cl):
    """(balance, available) in USD from wallet balances."""
    r = cl._p("GET", "/v2/wallet/balances")
    for x in r.get("result") or []:
        if x.get("asset_symbol") == "USD":
            return float(x.get("balance") or 0), float(x.get("available_balance") or 0)
    raise RuntimeError("no USD wallet row")


def flat(cl):
    pos = cl._p("GET", "/v2/positions/margined").get("result") or []
    live = [p for p in pos if abs(float(p.get("size") or 0)) > 0]
    oo = cl._p("GET", "/v2/orders", {"states": "open,pending"}).get("result") or []
    return (not live and not oo), len(live), len(oo)


def window_ok():
    t = now_ist(); m = t.hour * 60 + t.minute
    return not (22 * 60 + 30 <= m <= 23 * 60 + 50)


def check(cs):
    ids = {a: user_id(cs[a]) for a in (SRC, DST)}
    b_src, av_src = usd(cs[SRC]); b_dst, av_dst = usd(cs[DST])
    ok_flat, npos, nord = flat(cs[SRC])
    print("user ids   %s=%s  %s=%s" % (SRC, ids[SRC], DST, ids[DST]))
    print("%-10s balance %.2f  available %.2f USD" % (SRC, b_src, av_src))
    print("%-10s balance %.2f  available %.2f USD" % (DST, b_dst, av_dst))
    print("%s flat: %s (positions %d, open orders %d)" % (SRC, ok_flat, npos, nord))
    print("time window ok (not 22:30-23:50 IST): %s" % window_ok())
    problems = []
    if not ok_flat:
        problems.append("%s is not flat" % SRC)
    if av_src < 150:
        problems.append("%s available below USD 150" % SRC)
    if not window_ok():
        problems.append("inside the night window 22:30-23:50 IST")
    return ids, (b_src, av_src, b_dst, av_dst), problems


def move(cs, frm, to, ids, tag):
    """One transfer with the main key. Verified from balances; never retried here."""
    b0 = usd(cs[frm])[0]; d0 = usd(cs[to])[0]
    body = {"transferrer_user_id": ids[frm], "transferee_user_id": ids[to], "asset_symbol": "USD", "amount": AMOUNT}
    err = None
    try:
        r = cs["main"]._p("POST", PATH, body=body)
        log_row(tag, "%s->%s %s USD" % (frm, to, AMOUNT), json.dumps(r)[:300])
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, str(e)[:300])
        log_row(tag, "%s->%s %s USD" % (frm, to, AMOUNT), "EXC " + err)
    for _ in range(6):                      # up to ~30 s for the wallets to settle
        time.sleep(5)
        b1 = usd(cs[frm])[0]; d1 = usd(cs[to])[0]
        if abs((b0 - b1) - float(AMOUNT)) < 0.5 and abs((d1 - d0) - float(AMOUNT)) < 0.5:
            log_row(tag, "verified", "%s %.2f->%.2f  %s %.2f->%.2f" % (frm, b0, b1, to, d0, d1))
            return True, "%s %.2f -> %.2f, %s %.2f -> %.2f USD" % (frm, b0, b1, to, d0, d1)
    return False, err or "balances did not change as expected"


def run(back_only=False):
    cs = clients()
    ids, bal, problems = check(cs)
    st = load_state()
    if not back_only:
        if st.get("stage"):
            print("a previous test left state '%s' - read: python3 transfer_test.py status. Nothing moved. "
                  "(To run the test again on purpose, Claude clears state/transfer_test.json first.)" % st.get("stage"))
            return
        if problems:
            tg("TRANSFER TEST not started: " + "; ".join(problems) + ". Nothing moved.")
            return
        tg("TRANSFER TEST starting: Rs 5,000 (USD %s) %s -> %s now, back after 30 minutes." % (AMOUNT, SRC, DST))
        ok, msg = move(cs, SRC, DST, ids, "out")
        if not ok:
            save_state({"stage": "out_failed", "msg": msg, "t": time.time()})
            tg("TRANSFER TEST: the first transfer did NOT go through (%s). No money should have moved - please check Delta once. Nothing retried." % msg)
            return
        due = time.time() + WAIT_S
        save_state({"stage": "out_done", "due": due, "ids": ids})
        tg("TRANSFER TEST step 1 done and verified: %s. Return planned at %s IST." % (msg, (now_ist() + dt.timedelta(seconds=WAIT_S)).strftime("%H:%M")))
        while time.time() < due:
            time.sleep(20)
    else:
        if st.get("stage") != "out_done":
            print("state is %s - the return leg only runs after a verified first transfer." % st.get("stage"))
            return
    ok, msg = move(cs, DST, SRC, ids, "back")
    if ok:
        save_state({"stage": "finished", "t": time.time(), "msg": msg})
        tg("TRANSFER TEST finished: the server CAN move money between sub-accounts. Return verified: %s." % msg)
    else:
        save_state({"stage": "back_failed", "msg": msg, "t": time.time(), "ids": ids})
        tg("TRANSFER TEST: step 2 (return of Rs 5,000 to serverbot) FAILED (%s). The Rs 5,000 is still in ladder9. Nothing retried - tell Claude." % msg)


def main():
    a = sys.argv[1:] or ["check"]
    if a[0] == "status":
        print(json.dumps(load_state(), indent=1)); return
    if a[0] == "check":
        ids, bal, problems = check(clients())
        print("PROBLEMS: " + "; ".join(problems) if problems else "check OK - nothing moved")
        return
    if a[0] in ("run", "back"):
        if "--yes-move" not in a:
            print("needs --yes-move (this moves real money)"); return
        run(back_only=(a[0] == "back")); return
    print(__doc__)


if __name__ == "__main__":
    main()
