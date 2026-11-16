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
There is NO instruction to buy, sell, exit, change the account, the keys or the code.

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


ACTIONS = dict(status=do_status, pause=do_pause, resume=do_resume, wing=do_wing, ceiling=do_ceiling, autosize=do_autosize,
               clear_halt=do_clear_halt, restart=do_restart, tail=do_tail, log=do_log)


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
TG_HELP = ("More commands: /hedge = hedge now | /hedge on | /hedge off | /hedge 6 (percent) | /base = base and automatic size | "
           "/log = last trades | /services = are the bots running | /clearhalt | /exit = buy back everything now (asks to confirm)")


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
        B.MODE = "LIVE"
        B.Notifier().send("LETTERBOX " + subject, body)
    except Exception as e:
        print("email failed:", type(e).__name__)
    try:
        import nightwatch as NW
        NW.tg_send(("LETTERBOX %s\n%s" % (subject, body))[:900])
    except Exception as e:
        print("telegram failed:", type(e).__name__)


def look():
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
