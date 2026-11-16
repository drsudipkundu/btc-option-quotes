#!/usr/bin/env python3
"""letterbox (16-Nov-2026) - a way to change SETTINGS on the server without the PC. It NEVER places an order itself.

Every 2 minutes (cron) the server looks at one small file in Sudip's GitHub repository
(drsudipkundu/btc-option-quotes : server/letterbox/inbox.json). Only people who can write to that repository (Sudip, and Claude
working for him) can put an instruction there. Only the instructions in the FIXED LIST below are accepted; anything else is
refused and reported. Each instruction runs once (by its id), must be younger than 6 hours, and the answer goes by email
(subject "LETTERBOX ...") and a short line on Telegram.

  status                 full status report (settings, services, account, last log lines)
  pause / resume         no new night sales / allow them again            (same as the Pause button)
  wing N                 always-on hedge: N % beyond every sale, 0 = off  (N = 0 or 1..15)
  ceiling X [date]       automatic base: ceiling X BTC (0 = old rule), optional start date YYYY-MM-DD
  autosize on|off|show   automatic base on / off / what it would do now
  clear_halt             clear a position-mismatch halt (only when nothing is open)
  restart NAME           restart one service: nightlive (only when nothing is open), nightbot, shadowbot, variantbot, ui
  tail NAME [n]          last n lines (max 80) of a file in logs/
  log                    last rows of the live trade log
  orders                 READ ONLY: orders resting on Delta now (e.g. the 10 % buy-back orders)
  fills [n]              READ ONLY: last n (max 40) fills with price and fee, from Delta's own record
  quote SYMBOL           READ ONLY: bid / ask / mark and the top of the order book of one option (C-BTC-67200-171126) or BTCUSD
  chain C|P              READ ONLY: tonight's listed calls or puts within 10 % of the BTC price: bid, ask, mark
  install NAME           ASKS Sudip on Telegram to approve running the installer server/NAME (install_*.sh) taken from the very
                         repository version that carried the instruction. Nothing runs unless he answers /install yes within
                         30 minutes. Then the installer runs with its own safety rules; its output comes by email.
There is NO instruction to buy, sell, exit, or change the account or the keys.

The same actions serve the Telegram commands /hedge /base /log /services /clearhalt /exit (see telegram()).
  venv/bin/python letterbox.py            one look (what cron runs)
  venv/bin/python letterbox.py --do status      run one instruction now and print the answer (no email)
"""
import os, sys, json, re, time, subprocess, shutil, datetime as dt

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
REPO = "drsudipkundu/btc-option-quotes"
INBOX = "server/letterbox/inbox.json"
ST_F = os.path.join(HOME, "state", "letterbox.json")
PY = os.path.join(HOME, "venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable
SERVICES = ("nightlive", "nightbot", "shadowbot", "variantbot", "ui", "ladderlive")
RESTARTABLE = ("nightlive", "nightbot", "shadowbot", "variantbot", "ui")
MAX_AGE_S = 6 * 3600
PEND_F = os.path.join(HOME, "state", "letterbox_pending.json")
APPROVE_S = 30 * 60


def jload(p, d=None):
    try:
        return json.load(open(p))
    except Exception:
        return {} if d is None else d


def jsave(p, v):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(v, open(p + ".tmp", "w"))
    os.replace(p + ".tmp", p)


def sh(args, timeout=60):
    """run a fixed program with a list of arguments (no shell); returns its output"""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=HOME)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return "could not run (%s)" % type(e).__name__


def tail(path, n):
    try:
        with open(path, errors="replace") as f:
            return "".join(f.readlines()[-n:]).rstrip()
    except Exception:
        return "(no such file)"


def night_cfg():
    return jload(os.path.join(HOME, "state", "night_live_cfg.json"))


def night_state():
    return jload(os.path.join(HOME, "state", "night_nlive.json"))


def open_legs():
    return [l for l in night_state().get("legs", []) if not l.get("closed")]


# ---------------------------------------------------------------- the fixed list of actions
def do_pause(a):
    import control
    control.set_state("nlive", "paused")
    return "PAUSED: no new night sales. An open position keeps its resting buy-back and its hedge."


def do_resume(a):
    import control
    control.set_state("nlive", "running")
    return "RESUMED: night sales allowed again."


def do_wing(a):
    if len(a) != 1 or not re.fullmatch(r"\d{1,2}(\.\d)?", a[0]):
        return "REFUSED: give one number, 0 (off) or 1 to 15 (percent)"
    v = float(a[0])
    if not (v == 0 or 1 <= v <= 15):
        return "REFUSED: 0 (off) or 1 to 15 percent"
    sh([PY, "nightlive.py", "--wing", a[0]])
    w = float(night_cfg().get("wing") or 0)
    return "HEDGE is now %s (used from the next sale)." % (("ON: far option %.1f %% beyond every sale" % (w * 100)) if w else "OFF")


def do_ceiling(a):
    if not a or not re.fullmatch(r"0|0?\.\d{1,2}", a[0]) or (len(a) > 1 and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a[1])) or len(a) > 2:
        return "REFUSED: give the ceiling in BTC (0 = old rule, or 0.01 to 0.30) and optionally a start date YYYY-MM-DD"
    return "AUTOMATIC BASE " + sh([PY, "autosize.py", "--ceiling"] + a)


def do_autosize(a):
    if a not in (["on"], ["off"], ["show"]):
        return "REFUSED: autosize on | off | show"
    return sh([PY, "autosize.py", "--" + a[0]], 90)


def do_clear_halt(a):
    if open_legs():
        return "REFUSED: a night position is open. Clear the halt after it is closed."
    if not night_state().get("halt"):
        return "There is no halt."
    out = sh([PY, "nightlive.py", "--clear-halt"])
    return out.splitlines()[0][:80] + " | " + do_restart(["nightlive"])


def do_restart(a):
    if len(a) != 1 or a[0] not in RESTARTABLE:
        return "REFUSED: restart one of %s" % ", ".join(RESTARTABLE)
    if a[0] == "nightlive" and open_legs():
        return "REFUSED: a night position is open; the live seller is not restarted now."
    sh(["sudo", "-n", "systemctl", "restart", a[0]])
    time.sleep(5)
    return "%s restarted: now %s" % (a[0], sh(["systemctl", "is-active", a[0]]))


def do_tail(a):
    if not a or not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", a[0]) or a[0].startswith(".") or len(a) > 2:
        return "REFUSED: tail NAME [n] - NAME is a file in logs/"
    n = 30
    if len(a) == 2:
        if not re.fullmatch(r"\d{1,2}", a[1]):
            return "REFUSED: n is 1 to 80"
        n = max(1, min(80, int(a[1])))
    return "last %d lines of logs/%s\n%s" % (n, a[0], tail(os.path.join(HOME, "logs", a[0]), n))


def do_log(a):
    return "last rows of the live trade log\n" + tail(os.path.join(HOME, "logs", "trades_night_nlive.csv"), 12)


def services_text():
    return " | ".join("%s %s" % (s, sh(["systemctl", "is-active", s])) for s in SERVICES)


def hedge_text():
    w = float(night_cfg().get("wing") or 0)
    return "Hedge: %s" % (("ON, far option %.1f %% beyond every sale" % (w * 100)) if w else "OFF")


def base_text():
    c, a = night_cfg(), jload(os.path.join(HOME, "state", "autosize.json"))
    ceil = ("ceiling %.2f BTC from %s" % (a["ceiling"], dt.datetime.fromtimestamp(a.get("ceiling_from_ts", 0), IST).strftime("%d-%b"))) if a.get("ceiling") else "no ceiling (old rule)"
    return "Base now %.2f BTC, armed %s, rules %s. Automatic base: %s, %s.\nIf it ran now: %s" % (
        float(c.get("base", 0)), c.get("armed"), c.get("rule", "v4asl"), "ON" if a.get("on", True) else "OFF", ceil,
        sh([PY, "autosize.py", "--show"], 90)[-400:])


def do_status(a):
    now = dt.datetime.now(IST)
    c, S = night_cfg(), night_state()
    L = ["SERVER STATUS %s IST" % now.strftime("%d-%b-%Y %H:%M"), "", "Services: " + services_text()]
    try:
        import control
        L.append("Live seller switch: %s" % control.get("nlive")["state"])
    except Exception as e:
        L.append("Live seller switch: unreadable (%s)" % type(e).__name__)
    L += ["Live seller settings: armed %s, base %s BTC, rules %s, account %s" % (c.get("armed"), c.get("base"), c.get("rule", "v4asl"), c.get("acct")),
          hedge_text(), "Halt: %s" % (S.get("halt") or "none"),
          "Night %s | last finished night: %s | running total %.2f USD over %s nights" % (
              S.get("night"), json.dumps(S.get("last_night") or {}), float(S.get("total_pnl") or 0), S.get("nights", "?")),
          "Open legs in the bot's record: " + ("; ".join("%s %s %s BTC @ %s (%s)" % ("SOLD" if l["dir"] == "S" else "BOUGHT", l["sym"], l["qty"], l["entry"], l.get("kind"))
                                                         for l in open_legs()) or "none"),
          "Size limits: %s" % json.dumps(jload(os.path.join(HOME, "state", "limits.json"))), ""]
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HOME, ".env"))
        import nightwatch as NW
        pos, b0, spot = NW.read_account()
        L.append("Account (read only): BTC %.0f | balance %.2f USD | available %.2f USD" % (spot, NW.f(b0.get("balance")), NW.f(b0.get("available_balance"))))
        ps = ["%s %s @ %s mark %s" % (p.get("product_symbol"), p.get("size"), p.get("entry_price"), p.get("mark_price")) for p in pos if NW.f(p.get("size"))]
        L.append("Positions on Delta: " + (" | ".join(ps) if ps else "none"))
    except Exception as e:
        L.append("Account: could not be read (%s)" % type(e).__name__)
    L += ["", base_text(), ""]
    try:
        du = shutil.disk_usage(HOME)
        L.append("Server: disk free %.1f GB of %.1f GB | load %.2f" % (du.free / 1e9, du.total / 1e9, os.getloadavg()[0]))
    except Exception:
        pass
    for name, n in (("nightlive.log", 12), ("trades_night_nlive.csv", 8), ("autosize.csv", 3), ("wingpaper.csv", 2), ("backup.log", 2)):
        L += ["", "--- last %d lines of logs/%s" % (n, name), "\n".join(x[:260] for x in tail(os.path.join(HOME, "logs", name), n).splitlines())]
    return "\n".join(L)


# ---------------------------------------------------------------- READ-ONLY looks at Delta (GET requests only)
def _delta():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HOME, ".env"))
    from liveorders import Live, Pub
    return Live(str(night_cfg().get("acct") or "serverbot")), Pub()


def _f(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def _t(x):
    """Delta time (text or microseconds) -> IST text"""
    try:
        if isinstance(x, (int, float)) or str(x).isdigit():
            v = float(x)
            while v > 4e9:
                v /= 1000.0
            return dt.datetime.fromtimestamp(v, IST).strftime("%d-%b %H:%M:%S")
        return dt.datetime.fromisoformat(str(x).replace("Z", "+00:00")).astimezone(IST).strftime("%d-%b %H:%M:%S")
    except Exception:
        return str(x)[:19]


def do_orders(a):
    lv, _ = _delta()
    r = lv._p("GET", "/v2/orders", {"states": "open,pending"}).get("result") or []
    if not r:
        return "No orders are resting on Delta."
    L = ["%d order(s) resting on Delta:" % len(r)]
    for o in r[:40]:
        L.append("%s %s %s  size %s (unfilled %s) @ %s  %s%s  placed %s" % (
            o.get("product_symbol"), str(o.get("side", "")).upper(), o.get("order_type", ""), o.get("size"), o.get("unfilled_size"),
            o.get("limit_price") or o.get("stop_price"), o.get("state"), " reduce-only" if o.get("reduce_only") else "", _t(o.get("created_at"))))
    return "\n".join(L)


def do_fills(a):
    n = 15
    if a:
        if len(a) != 1 or not re.fullmatch(r"\d{1,2}", a[0]):
            return "REFUSED: fills [n] - n is 1 to 40"
        n = max(1, min(40, int(a[0])))
    lv, _ = _delta()
    r = lv._p("GET", "/v2/fills", {"page_size": n}).get("result") or []
    if not r:
        return "Delta shows no fills."
    L = ["last %d fill(s) from Delta (newest first):" % len(r[:n])]
    for x in r[:n]:
        L.append("%s  %s %s  %s contracts @ %s  fee %s  %s" % (
            _t(x.get("created_at")), x.get("product_symbol"), str(x.get("side", "")).upper(), x.get("size"), x.get("price"),
            x.get("commission"), x.get("role") or ""))
    return "\n".join(L)


def do_quote(a):
    if len(a) != 1 or not re.fullmatch(r"(?:[CP]-BTC-\d{4,7}-\d{6}|BTCUSD)", a[0].upper()):
        return "REFUSED: quote SYMBOL - like C-BTC-67200-171126 or BTCUSD"
    sym = a[0].upper()
    _, pub = _delta()
    t = pub._http("GET", "/v2/tickers/%s" % sym)["result"]
    q = t.get("quotes") or {}
    L = ["%s  bid %s  ask %s  mark %s  BTC %s  %s" % (sym, q.get("best_bid"), q.get("best_ask"), t.get("mark_price"), t.get("spot_price"),
                                                   ("mark IV %s" % q.get("mark_iv")) if q.get("mark_iv") else "")]
    try:
        b = pub._http("GET", "/v2/l2orderbook/%s" % sym, {"depth": 5})["result"]
        L.append("buyers : " + ("  ".join("%s x%s" % (x.get("price"), x.get("size")) for x in (b.get("buy") or [])[:5]) or "none"))
        L.append("sellers: " + ("  ".join("%s x%s" % (x.get("price"), x.get("size")) for x in (b.get("sell") or [])[:5]) or "none"))
    except Exception as e:
        L.append("order book not read (%s)" % type(e).__name__)
    return "\n".join(L)


def do_chain(a):
    if len(a) != 1 or a[0].upper() not in ("C", "P"):
        return "REFUSED: chain C  or  chain P"
    typ = "CE" if a[0].upper() == "C" else "PE"
    from nightlogic import next_expiry_ts
    _, pub = _delta()
    spot = _f(pub._http("GET", "/v2/tickers/BTCUSD")["result"].get("spot_price"))
    exp = next_expiry_ts(time.time())
    ch = sorted([o for o in pub.chain(exp) if o["typ"] == typ and abs(o["strike"] - spot) <= 0.10 * spot], key=lambda o: o["strike"])
    L = ["%s expiring %s IST, BTC %.0f  (strike: bid / ask / mark, distance)" % ("CALLS" if typ == "CE" else "PUTS",
         dt.datetime.fromtimestamp(exp, IST).strftime("%d-%b %H:%M"), spot)]
    for o in ch:
        if (typ == "CE") == (o["strike"] >= spot):                # out-of-the-money side only
            L.append("%.0f: %s / %s / %.1f  (%+.1f %%)" % (o["strike"], o["bid"] or "-", o["ask"] or "-", o["mark"], (o["strike"] / spot - 1) * 100))
    return "\n".join(L[:70])


# ---------------------------------------------------------------- update of the code, only with Sudip's yes on Telegram
def request_install(cid, args, note, sha):
    if len(args) != 1 or not re.fullmatch(r"install_[a-z0-9_]{1,40}\.sh", args[0]):
        return "REFUSED: install NAME - NAME must be an installer file like install_xyz.sh"
    if not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
        return "REFUSED: no repository version"
    note = re.sub(r"[^\x20-\x7e]", " ", str(note or ""))[:400] or "(no description given)"
    jsave(PEND_F, dict(id=cid, script=args[0], sha=sha, note=note, asked=time.time(), approved=0, done=False))
    return ("UPDATE WAITING FOR YOUR YES\nWhat: %s\nInstaller: %s (version %s)\n"
            "Reply  /install yes  within 30 minutes to install it.  /install no  drops it. No reply = nothing happens." % (note, args[0], sha[:7]))


def install_text():
    p = jload(PEND_F)
    if not p or p.get("done"):
        return "No update is waiting."
    left = APPROVE_S - (time.time() - p.get("asked", 0))
    if p.get("approved"):
        return "Update '%s' is approved and starts within 2 minutes." % p.get("script")
    if left <= 0:
        return "The update '%s' was not answered in 30 minutes and has lapsed. Ask Claude to send it again." % p.get("script")
    return "Waiting for your yes (%d minutes left): %s\nInstaller %s. Reply /install yes or /install no." % (left // 60, p.get("note"), p.get("script"))


def install_answer(yes):
    p = jload(PEND_F)
    if not p or p.get("done") or p.get("approved"):
        return install_text()
    if time.time() - p.get("asked", 0) > APPROVE_S:
        return install_text()
    if not yes:
        p["done"] = True
        jsave(PEND_F, p)
        return "Update dropped. Nothing was installed."
    p["approved"] = time.time()
    jsave(PEND_F, p)
    return "APPROVED. The update '%s' starts within 2 minutes; the result comes here and by email." % p["script"]


def run_approved():
    p = jload(PEND_F)
    if not p or p.get("done") or not p.get("approved"):
        return
    p["done"] = True
    jsave(PEND_F, p)                                       # marked BEFORE running: never twice
    if time.time() - p["approved"] > 900:
        answer("%s install NOT RUN" % p["id"], "the approval is older than 15 minutes - ask Claude to send the update again")
        return
    try:
        body = curl("https://raw.githubusercontent.com/%s/%s/server/%s" % (REPO, p["sha"], p["script"]))
        f = os.path.join(HOME, "state", "letterbox_run.sh")
        open(f, "w").write(body)
        r = subprocess.run(["bash", f, p["sha"]], capture_output=True, text=True, timeout=900, cwd=HOME)
        out = (r.stdout + "\n" + r.stderr).strip()
        ok = r.returncode == 0
    except Exception as e:
        out, ok = "could not run the installer: %s %s" % (type(e).__name__, str(e)[:200]), False
    print(dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"), p["id"], "install", p["script"], p["sha"][:7], "->", "OK" if ok else "FAILED")
    lines = out.splitlines()
    answer("%s install %s %s" % (p["id"], p["script"], "DONE" if ok else "FAILED / REFUSED"),
           "%s\n\n%s" % ("\n".join(lines[-6:]), "\n".join(lines[-80:])))


ACTIONS = dict(status=do_status, pause=do_pause, resume=do_resume, wing=do_wing, ceiling=do_ceiling, autosize=do_autosize,
               clear_halt=do_clear_halt, restart=do_restart, tail=do_tail, log=do_log,
               orders=do_orders, fills=do_fills, quote=do_quote, chain=do_chain)


def run(do, args):
    if do not in ACTIONS:
        return "REFUSED: '%s' is not in the fixed list (%s)" % (str(do)[:30], ", ".join(sorted(ACTIONS)))
    args = [str(x) for x in (args or [])]
    if len(args) > 3 or any(len(x) > 60 for x in args):
        return "REFUSED: too many or too long arguments"
    try:
        return ACTIONS[do](args)
    except Exception as e:
        return "FAILED: %s %s" % (type(e).__name__, str(e)[:200])


# ---------------------------------------------------------------- Telegram (called by nightwatch.py, only from Sudip's own chat)
TG_CMDS = ("/hedge", "/base", "/log", "/services", "/clearhalt", "/exit", "/install", "/orders", "/fills", "/quote", "/chain")
TG_HELP = ("More commands: /hedge = hedge now | /hedge on | /hedge off | /hedge 6 (percent) | /base = base and automatic size | "
           "/log = last trades | /services = are the bots running | /clearhalt | /exit = buy back everything now (asks to confirm) | /install = update waiting for your yes | /orders = orders resting on Delta | /fills = last fills | /quote C-BTC-67200-171126 | /chain c or /chain p = tonight's strikes")


def telegram(text, st):
    p = text.split()
    c, a = p[0], p[1:]
    if c == "/hedge":
        if not a:
            return hedge_text() + "\nChange: /hedge on, /hedge off, /hedge 6"
        return run("wing", ["4" if a[0] == "on" else "0" if a[0] == "off" else a[0]])
    if c == "/base":
        return base_text()
    if c == "/log":
        return do_log([])[-3500:]
    if c == "/services":
        return services_text()
    if c == "/clearhalt":
        return run("clear_halt", [])
    if c in ("/orders", "/fills", "/quote", "/chain"):
        return run(c[1:], [x.upper() if c in ("/quote", "/chain") else x for x in a])[-3500:]
    if c == "/install":
        return install_text() if not a else install_answer(a == ["yes"]) if a in (["yes"], ["no"]) else "Reply /install yes or /install no."
    if c == "/exit":
        legs = open_legs()
        if not legs:
            return "Nothing is open - nothing to exit."
        if a == ["yes"] and time.time() - st.get("exit_ask", 0) <= 180:
            st["exit_ask"] = 0
            import control
            control.set_state("nlive", "stopped")
            return ("EXIT STARTED: the live seller buys back every sold option now (and then sells the far options). You get a message for each. "
                    "New sales stay OFF until you send /resume.")
        st["exit_ask"] = time.time()
        return ("EXIT asks: buy back %d open leg(s) NOW at the market's offers and stop new sales?\n%s\nSend  /exit yes  within 3 minutes to do it. Anything else = nothing happens."
                % (len(legs), "; ".join("%s %s %s" % ("SOLD" if l["dir"] == "S" else "BOUGHT", l["sym"], l["qty"]) for l in legs)))
    return TG_HELP


# ---------------------------------------------------------------- the letterbox itself
def curl(url, extra=()):
    r = subprocess.run(["curl", "-fsS", "-4", "--max-time", "20"] + list(extra) + [url], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError("curl %d" % r.returncode)
    return r.stdout


def answer(subject, body):
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HOME, ".env"))
        import bot as B
        B.Notifier()._send_now("[DeltaBot LIVE] LETTERBOX " + subject, body)     # sent before this short program ends
    except Exception as e:
        print("email failed:", type(e).__name__)
    try:
        import nightwatch as NW
        NW.tg_send(("LETTERBOX %s\n%s" % (subject, body))[:900])
    except Exception as e:
        print("telegram failed:", type(e).__name__)


def look():
    import fcntl
    lock = open(os.path.join(HOME, "state", "letterbox.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return                                             # an earlier look (an installer) is still running
    run_approved()
    st = jload(ST_F)
    sha = curl("https://api.github.com/repos/%s/commits/main" % REPO, ["-H", "Accept: application/vnd.github.sha"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("bad answer from GitHub")
    if sha == st.get("sha"):
        return
    try:
        box = json.loads(curl("https://raw.githubusercontent.com/%s/%s/%s" % (REPO, sha, INBOX)))
        cmds = box.get("commands", []) if isinstance(box, dict) else []
    except Exception:
        cmds = []
    first = "sha" not in st
    done = st.get("done", [])
    now = time.time()
    for c in cmds[:10]:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id", ""))[:40]
        if not cid or cid in done:
            continue
        done.append(cid)
        st.update(sha=sha, done=done[-200:])
        jsave(ST_F, st)                                    # marked BEFORE running: never twice
        if first:
            continue                                       # the very first look only notes what is already there
        try:
            age = now - float(c.get("t", 0))
        except Exception:
            age = 1e9
        do = str(c.get("do", ""))
        if not (-600 <= age <= MAX_AGE_S):
            answer("%s REFUSED" % cid, "instruction '%s' is older than 6 hours (or has no time) - not done" % do[:30])
            continue
        if do == "install":
            res = request_install(cid, [str(x) for x in c.get("args", [])] if isinstance(c.get("args"), list) else [], c.get("note"), sha)
        else:
            res = run(do, c.get("args") if isinstance(c.get("args"), list) else [])
        print(dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"), cid, do, c.get("args"), "->", res.splitlines()[0][:150] if res else "")
        answer("%s %s" % (cid, do), res)
    st.update(sha=sha, done=done[-200:])
    jsave(ST_F, st)


if __name__ == "__main__":
    if "--do" in sys.argv:
        i = sys.argv.index("--do")
        print(run(sys.argv[i + 1], sys.argv[i + 2:]))
    else:
        try:
            look()
        except Exception as e:
            print(dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"), "look failed:", type(e).__name__, e)
