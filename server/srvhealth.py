"""Server health page for My Bots (/server). Read only: CPU, memory, disk, uptime, services, bot heartbeats, logs, backups.
Added 19-Nov-2026 at Sudip's request ("a tab showing server health or usage status on my bot page")."""
import os, time, shutil, subprocess, html, glob
from datetime import datetime, timezone, timedelta
HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
IST = timezone(timedelta(hours=5, minutes=30))
E = html.escape
SERVICES = [("nightlive", "Live night seller (real money)"), ("nightbot", "Night paper copies"), ("shadowbot", "Shadow fleet"),
            ("variantbot", "Ladder paper variants"), ("ladderlive", "Live ladder"), ("ui", "This page"), ("caddy", "HTTPS front door")]
BEATS = [("logs/nightlive.log", "Live night seller", 300), ("logs/night.log", "Night paper copies", 300), ("logs/bot.log", "Ladder paper", 600)]


def _sh(cmd, t=3):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:
        return ""


def _cpu_pct():
    def rd():
        v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
        return sum(v), v[3] + (v[4] if len(v) > 4 else 0)
    try:
        a, ia = rd(); time.sleep(0.4); b, ib = rd()
        return 100.0 * (1 - (ib - ia) / max(1, b - a))
    except Exception:
        return None


def _mem():
    m = {}
    try:
        for ln in open("/proc/meminfo"):
            k, v = ln.split(":"); m[k] = int(v.split()[0]) * 1024
    except Exception:
        pass
    return m


def _age(sec):
    if sec is None: return "never"
    sec = int(sec)
    if sec < 90: return "%d s ago" % sec
    if sec < 5400: return "%d min ago" % (sec // 60)
    if sec < 172800: return "%.1f h ago" % (sec / 3600)
    return "%.1f days ago" % (sec / 86400)


def _gb(b): return "%.1f GB" % (b / 1e9)


def _dot(state):
    c = {"ok": "#1a7f37", "warn": "#b58100", "bad": "#c62828"}[state]
    return '<span style="display:inline-block;width:10px;height:10px;border-radius:5px;background:%s;margin-right:6px"></span>' % c


def page_html():
    now = time.time()
    cpu = _cpu_pct(); ncpu = os.cpu_count() or 1
    try: la = os.getloadavg()
    except Exception: la = (0, 0, 0)
    m = _mem(); mt, ma = m.get("MemTotal", 0), m.get("MemAvailable", 0); st, sf = m.get("SwapTotal", 0), m.get("SwapFree", 0)
    du = shutil.disk_usage(HOME)
    try: up = float(open("/proc/uptime").read().split()[0])
    except Exception: up = 0
    ntp = _sh(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    mem_pct = 100.0 * (1 - ma / mt) if mt else 0; disk_pct = 100.0 * du.used / du.total
    lvl = lambda v, w, b: "bad" if v >= b else ("warn" if v >= w else "ok")
    cards = [("CPU now", "%.0f %%" % cpu if cpu is not None else "?", lvl(cpu or 0, 70, 90), "%d core(s); load %.2f / %.2f / %.2f (1/5/15 min)" % (ncpu, *la)),
             ("Memory", "%.0f %%" % mem_pct, lvl(mem_pct, 80, 92), "%s free of %s; swap used %s" % (_gb(ma), _gb(mt), _gb(st - sf))),
             ("Disk", "%.0f %%" % disk_pct, lvl(disk_pct, 80, 92), "%s free of %s" % (_gb(du.free), _gb(du.total))),
             ("Up for", "%.1f days" % (up / 86400), "ok", "clock synced: %s" % ("yes" if ntp == "yes" else (ntp or "?")))]
    h = ['<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30">'
         '<title>Server health</title><style>body{font-family:system-ui,sans-serif;margin:0;background:#f4f5f7;color:#1c2430}.w{max-width:900px;margin:0 auto;padding:12px 14px 40px}'
         '.cards{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}.card{flex:1;min-width:150px;background:#fff;border-radius:12px;padding:12px;box-shadow:0 1px 3px #0001}'
         '.big{font-size:24px;font-weight:600}.m{color:#6b7684;font-size:12px}.row{background:#fff;border-radius:12px;padding:12px;margin:10px 0;box-shadow:0 1px 3px #0001}'
         'table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:5px 3px;text-align:left;border-bottom:1px solid #e5e8ec}a{color:#1c2430}</style></head><body><div class="w">',
         '<p><a href="/">&larr; My Bots</a></p><h2>&#128421; Server health</h2><p class="m">%s IST &middot; refreshes every 30 s &middot; read only</p><div class="cards">' % datetime.now(IST).strftime("%d-%b-%Y %H:%M:%S")]
    for t, v, s, sub in cards:
        h.append('<div class="card"><div class="m">%s</div><div class="big">%s%s</div><div class="m">%s</div></div>' % (E(t), _dot(s), E(v), E(sub)))
    h.append('</div><div class="row"><b>Services</b><table><tr><th>Service</th><th>What</th><th>State</th><th>Running since</th><th>Memory</th></tr>')
    for name, what in SERVICES:
        state = _sh(["systemctl", "is-active", name]) or "unknown"
        props = dict(l.split("=", 1) for l in _sh(["systemctl", "show", name, "-p", "ActiveEnterTimestamp", "-p", "MemoryCurrent", "-p", "NRestarts"]).splitlines() if "=" in l)
        mem = props.get("MemoryCurrent", "")
        mem = ("%.0f MB" % (int(mem) / 1e6)) if mem.isdigit() else ""
        since = props.get("ActiveEnterTimestamp", "")
        nr = props.get("NRestarts", "")
        s = "ok" if state == "active" else ("warn" if state in ("activating", "reloading") else "bad")
        h.append("<tr><td>%s%s</td><td>%s</td><td>%s%s</td><td>%s</td><td>%s</td></tr>" % (_dot(s), E(name), E(what), E(state), (" (restarts %s)" % E(nr)) if nr and nr != "0" else "", E(since[4:20] if since else ""), E(mem)))
    h.append('</table></div><div class="row"><b>Bot heartbeats</b> <span class="m">(last line written to the bot\'s log)</span><table><tr><th>Bot</th><th>Last write</th></tr>')
    for p, what, lim in BEATS:
        fp = os.path.join(HOME, p)
        age = now - os.path.getmtime(fp) if os.path.exists(fp) else None
        s = "bad" if age is None or age > 3 * lim else ("warn" if age > lim else "ok")
        h.append("<tr><td>%s%s</td><td>%s</td></tr>" % (_dot(s), E(what), _age(age)))
    h.append('</table></div><div class="row"><b>Scheduled jobs and backups</b><table><tr><th>Log</th><th>Last write</th><th>Last line</th></tr>')
    for p in ("logs/backup.log", "logs/drivebackup.log", "logs/autosize.log", "logs/callmargin.log", "logs/letterbox.log", "logs/edgecheck.log"):
        fp = os.path.join(HOME, p)
        if not os.path.exists(fp): continue
        try: last = (open(fp, errors="replace").read().strip().splitlines() or [""])[-1][:110]
        except Exception: last = ""
        h.append("<tr><td>%s</td><td>%s</td><td class=\"m\">%s</td></tr>" % (E(os.path.basename(p)), _age(now - os.path.getmtime(fp)), E(last)))
    h.append('</table></div><div class="row"><b>Biggest folders</b><table><tr><th>Folder</th><th>Size</th></tr>')
    for d in ("logs", "state", "venv"):
        fp = os.path.join(HOME, d)
        if os.path.isdir(fp):
            h.append("<tr><td>%s</td><td>%s</td></tr>" % (E(d), E((_sh(["du", "-sh", fp], 8).split() or ["?"])[0])))
    top = _sh(["ps", "-eo", "rss,pcpu,comm,args", "--sort=-rss"]).splitlines()[1:7]
    h.append('</table></div><div class="row"><b>Top programs by memory</b><table><tr><th>Memory</th><th>CPU</th><th>Program</th></tr>')
    for ln in top:
        p = ln.split(None, 3)
        if len(p) >= 4:
            h.append("<tr><td>%.0f MB</td><td>%s %%</td><td class=\"m\">%s</td></tr>" % (int(p[0]) / 1024, E(p[1]), E(p[3][:90])))
    h.append('</table></div><p class="m">Green = fine, amber = keep an eye, red = needs attention. CPU/memory/disk amber from 70/80/80 %, red from 90/92/92 %. '
             'A bot heartbeat turns amber when its log is quiet for longer than its normal beat (5-10 min), red at 3 times that.</p></div></body></html>')
    return "".join(h).encode()
