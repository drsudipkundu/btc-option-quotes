#!/usr/bin/env python3
"""Server watchdog (read-only). 5-Nov-2026.

Every 60 s it checks that the server and the live-money bots are healthy:
  * every ENABLED bot service is active (nightlive, ladderlive, deltabot, nightbot, ui, recorders ...)
  * disk space, free memory, swap, load
  * Delta India public API reachable and the server clock is correct
  * the daily Google Drive copies (drivesync, backup_live) did not go stale
It sends an email when something goes wrong (once, then a reminder every 60 min) and a "recovered" email.
It also pings an OUTSIDE dead-man's-switch (healthchecks.io) once a minute while all is well. If the whole server,
its network, or this watchdog dies, the pings stop and the outside service emails you - the only alert that
still works when the server itself is dead.
It never trades and never touches any bot. Config (optional) in ~/deltabot/.env: HC_PING_URL=https://hc-ping.com/<uuid>
"""
import json, os, shutil, subprocess, sys, time, urllib.request, email.utils

H = os.path.expanduser("~/deltabot")
STATE = os.path.join(H, "state", "watchdog.json")
LOG = os.path.join(H, "logs", "watchdog.log")
REMIND_SEC = 3600
LOOP_SEC = 60
# live-money services: a problem here is CRITICAL (subject starts with [DeltaBot CRITICAL])
CRITICAL = {"nightlive", "ladderlive", "deltabot", "nightbot", "ui"}
# every service we know about; only those that are ENABLED on this server are watched
KNOWN = ["nightlive", "ladderlive", "deltabot", "nightbot", "ui", "shadowbot", "variantbot", "ladshadow",
         "skipweekly", "fundlog", "obook-recorder", "optbook-recorder"]
DISK_MIN_PCT = 15.0
MEM_MIN_MB = 80
LOAD_MAX = 6.0
CLOCK_MAX_SEC = 5
SYNC_MAX_AGE_H = 36


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%F %T"), msg))
        # keep the log small
        if os.path.getsize(LOG) > 2_000_000:
            with open(LOG) as f:
                tail = f.readlines()[-3000:]
            with open(LOG, "w") as f:
                f.writelines(tail)
    except Exception:
        pass


def load_env():
    try:
        for line in open(os.path.join(H, ".env")):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
    return r.stdout.strip()


def enabled_services():
    out = []
    for s in KNOWN:
        if sh("systemctl is-enabled %s 2>/dev/null" % s) == "enabled":
            out.append(s)
    return out


def check_services(problems):
    for s in enabled_services():
        st = sh("systemctl is-active %s" % s)
        if st != "active":
            problems.append(("svc_" + s, s in CRITICAL, "service %s is %s (should be active)" % (s, st or "unknown")))


def check_resources(problems):
    du = shutil.disk_usage("/")
    free_pct = du.free * 100.0 / du.total
    if free_pct < DISK_MIN_PCT:
        problems.append(("disk", False, "disk only %.0f%% free (%.1f GB left)" % (free_pct, du.free / 1e9)))
    mem = {}
    for line in open("/proc/meminfo"):
        k, v = line.split(":", 1)
        mem[k] = int(v.split()[0])
    avail_mb = mem.get("MemAvailable", 0) / 1024.0
    if avail_mb < MEM_MIN_MB:
        problems.append(("mem", False, "only %.0f MB memory available (server has 1 GB)" % avail_mb))
    la = os.getloadavg()[1]
    if la > LOAD_MAX:
        problems.append(("load", False, "5-minute load average %.1f is high" % la))


def check_delta(problems):
    try:
        req = urllib.request.Request("https://api.india.delta.exchange/v2/tickers/BTCUSD",
                                     headers={"User-Agent": "watchdog"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode())
            date_hdr = r.headers.get("Date")
        if not body.get("success"):
            problems.append(("delta_api", True, "Delta API answered but success=false"))
        if time.time() - t0 > 10:
            problems.append(("delta_slow", False, "Delta API is slow (%.1f s)" % (time.time() - t0)))
        if date_hdr:
            skew = abs(email.utils.parsedate_to_datetime(date_hdr).timestamp() - time.time())
            if skew > CLOCK_MAX_SEC:
                problems.append(("clock", True, "server clock is off by %.0f s versus Delta" % skew))
    except Exception as e:
        problems.append(("delta_api", True, "cannot reach Delta India API: %s" % str(e)[:120]))


def check_sync(problems):
    for name, path in (("drive sync", "logs/drivesync.log"), ("code+state backup", "logs/backup_live.log")):
        p = os.path.join(H, path)
        if not os.path.exists(p):
            if name == "drive sync":
                problems.append(("sync_" + name, False, "%s log missing" % name))
            continue  # backup log may not exist until the first night after install
        age_h = (time.time() - os.path.getmtime(p)) / 3600.0
        last = ""
        try:
            last = open(p).read().strip().splitlines()[-1]
        except Exception:
            pass
        if "FAILED" in last:
            problems.append(("sync_" + name, False, "%s: last run FAILED" % name))
        elif age_h > SYNC_MAX_AGE_H:
            problems.append(("sync_" + name, False, "%s has not run for %.0f hours" % (name, age_h)))


def send_mail(subject, body):
    try:
        sys.path.insert(0, H)
        os.chdir(H)
        import bot  # the existing bot module; its Notifier uses the Gmail settings in .env
        bot.Notifier()._send_now(subject, body)
        return True
    except Exception as e:
        log("mail failed: %s" % e)
        return False


def ping(ok, detail=""):
    url = os.environ.get("HC_PING_URL", "").strip()
    if not url:
        return
    try:
        u = url if ok else url.rstrip("/") + "/fail"
        req = urllib.request.Request(u, data=detail[:500].encode(), method="POST")
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        log("ping failed: %s" % e)


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"open": {}}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w"))
    os.replace(tmp, STATE)


def cycle(st, send=True):
    problems = []
    for fn in (check_services, check_resources, check_delta, check_sync):
        try:
            fn(problems)
        except Exception as e:
            problems.append(("check_" + fn.__name__, False, "watchdog check %s crashed: %s" % (fn.__name__, e)))
    now = time.time()
    cur = {k: (crit, msg) for k, crit, msg in problems}
    opened = st["open"]
    new, remind, cleared = [], [], []
    for k, (crit, msg) in cur.items():
        if k not in opened:
            opened[k] = {"since": now, "last_mail": now, "crit": crit, "msg": msg}
            new.append((crit, msg))
        else:
            opened[k]["msg"] = msg
            if now - opened[k]["last_mail"] >= REMIND_SEC:
                opened[k]["last_mail"] = now
                remind.append((crit, msg))
    for k in list(opened):
        if k not in cur:
            cleared.append(opened.pop(k)["msg"])
    if send and (new or remind):
        crit_any = any(c for c, _ in new + remind)
        lines = ["NEW:"] + ["  - " + m for _, m in new] + (["STILL OPEN:"] + ["  - " + m for _, m in remind] if remind else [])
        lines.append("")
        lines.append("All open problems: " + ("; ".join(v["msg"] for v in opened.values()) or "none"))
        send_mail("[DeltaBot %s] server watchdog: %d problem(s)" % ("CRITICAL" if crit_any else "WARNING", len(opened)),
                  "\n".join(lines))
    if send and cleared and not opened:
        send_mail("[DeltaBot] server watchdog: all clear", "Recovered:\n" + "\n".join("  - " + m for m in cleared))
    # outside dead-man's-switch: "ok" ping only when no CRITICAL problem is open
    crit_open = [v["msg"] for v in opened.values() if v["crit"]]
    ping(not crit_open, "; ".join(crit_open))
    log("ok" if not opened else "open: " + " | ".join(v["msg"] for v in opened.values()))
    return problems


def main():
    load_env()
    once = "--once" in sys.argv
    st = load_state()
    if once:
        probs = cycle(st, send="--mail" in sys.argv)
        print("watchdog: %d problem(s)" % len(probs))
        for k, crit, msg in probs:
            print(("CRITICAL " if crit else "warning  ") + msg)
        print("services watched:", ", ".join(enabled_services()))
        print("outside ping configured:", bool(os.environ.get("HC_PING_URL")))
        return
    log("watchdog started")
    while True:
        try:
            cycle(st)
            save_state(st)
        except Exception as e:
            log("cycle error: %s" % e)
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    main()
