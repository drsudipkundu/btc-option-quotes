"""Control-page "Live ladder" card (6-Nov-2026). Page /llive: status of every live-ladder key (v9 ladder, v10-v13),
and buttons: Arm / Disarm / Clear halt / Calls on-off. It only edits state/ladder_live_cfg.json (via ladderlive.put);
the ladderlive service reads that file every few seconds. Arming needs the key typed again (typo guard).
Same safety rules as the command line: one armed ladder per account; serverbot => shared, calls off."""
import os, json, time, html

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
ACCTS = ("serverbot", "ladder9")


def _ll():
    import ladderlive
    return ladderlive


def _state(k):
    try:
        d = json.load(open(os.path.join(HOME, "state", "live_%s_state.json" % k)))["ladder"]
        lots = d.get("lots", [])
        return d.get("cycle", 0), len(lots)
    except Exception:
        return 0, 0


def _held_btc(k):
    try:
        d = json.load(open(os.path.join(HOME, "state", "ladder_expected_%s.json" % _ll().load_cfg()[k]["acct"])))
        if d.get("key") == k:
            return d.get("BTCUSD", 0) * 0.001
    except Exception:
        pass
    return None


def action(q):
    """q = dict of query values: do, k, acct, confirm. Returns a short message."""
    LL = _ll()
    do, k = q.get("do", ""), q.get("k", "")
    if k not in LL.KEYS:
        return "unknown strategy"
    cfg = LL.load_cfg()
    if do == "arm":
        acct = q.get("acct", "")
        if acct not in ACCTS:
            return "unknown account"
        if q.get("confirm", "").strip().lower() != k:
            return "NOT armed: type the strategy name (%s) in the box to confirm" % k
        for k2, v2 in cfg.items():
            if k2 != k and v2["armed"] and v2["acct"] == acct:
                return "REFUSED: %s is already armed on %s" % (k2, acct)
        if cfg[k].get("halt"):
            return "REFUSED: it is halted - check the account, then Clear halt first"
        sh = acct == "serverbot"
        LL.put(k, armed=True, acct=acct, halt=None, shared=sh, **({"calls": False} if sh else {}))
        return "%s ARMED on %s%s" % (k, acct, " (shared with night seller, calls off)" if sh else "")
    if do == "disarm":
        LL.put(k, armed=False)
        return "%s disarmed (orders are cancelled by the service; BTC held stays)" % k
    if do == "clearhalt":
        LL.put(k, halt=None)
        return "halt cleared for %s" % k
    if do in ("callson", "callsoff"):
        if do == "callson" and cfg[k].get("shared"):
            return "calls cannot be on while sharing an account"
        LL.put(k, calls=(do == "callson"))
        return "calls %s for %s" % ("ON" if do == "callson" else "OFF", k)
    return "nothing done"


def page_html(msg=""):
    LL = _ll()
    cfg = LL.load_cfg()
    e = html.escape
    h = ['<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         '<title>Live ladder</title><style>body{font-family:system-ui,sans-serif;margin:12px;max-width:900px}'
         'table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #ddd;padding:5px 8px;text-align:left}th{background:#f1f5f9}'
         '.on{background:#dcfce7}.halt{background:#fee2e2}.box{background:#fef3c7;border-radius:8px;padding:8px 12px;margin:8px 0}'
         'button{margin:2px}input{width:90px}</style></head><body>'
         '<p><a href="/">&larr; Control page</a></p><h2>Live ladder (real money)</h2>']
    if msg:
        h.append('<div class="box"><b>%s</b></div>' % e(msg))
    h.append('<div class="box">Real orders only when a row is ARMED. Everything is disarmed by default. '
             'Account <b>serverbot</b> is shared with the night seller: calls stay off, and the ladder holds only BTCUSD futures. '
             'Before arming: account must hold 0 BTCUSD, enough margin, and the ladderlive service must have been restarted after the last update. '
             'The brake (max BTC held) is set on each strategy card of the main page.</div>')
    h.append('<table><tr><th>strategy</th><th>state</th><th>account</th><th>cycle / lots</th><th>BTC held (last check)</th><th>calls</th><th>halt</th><th>actions</th></tr>')
    for k in LL.KEYS:
        c = cfg[k]
        cyc, n = _state(k)
        hb = _held_btc(k)
        cls = "halt" if c["halt"] else ("on" if c["armed"] else "")
        st = "HALTED" if c["halt"] else ("ARMED" if c["armed"] else "disarmed")
        acts = []
        if c["armed"]:
            acts.append('<form method="post" action="/llive?do=disarm&k=%s" style="display:inline"><button>Disarm</button></form>' % k)
        else:
            sel = "".join('<option>%s</option>' % a for a in ACCTS)
            acts.append('<form method="post" style="display:inline" onsubmit="this.action=\'/llive?do=arm&k=%s&acct=\'+this.a.value+\'&confirm=\'+encodeURIComponent(this.c.value);'
                        'return confirm(\'ARM %s with REAL money on \'+this.a.value+\'?\')"><select name="a">%s</select> '
                        '<input name="c" placeholder="type %s"> <button>Arm</button></form>' % (k, k, sel, k))
        if c["halt"]:
            acts.append('<form method="post" action="/llive?do=clearhalt&k=%s" style="display:inline"><button>Clear halt</button></form>' % k)
        if not c.get("shared"):
            acts.append('<form method="post" action="/llive?do=%s&k=%s" style="display:inline"><button>Calls %s</button></form>' % (
                "callsoff" if c["calls"] else "callson", k, "OFF" if c["calls"] else "ON"))
        h.append('<tr class="%s"><td><b>%s</b></td><td>%s</td><td>%s%s</td><td>%s / %d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            cls, k, st, e(c["acct"]), " (shared)" if c.get("shared") else "", cyc, n,
            "-" if hb is None else "%.3f" % hb, "on" if c["calls"] else "off", e(str(c["halt"] or "")), " ".join(acts)))
    h.append('</table><p style="color:#64748b;font-size:12px">Command line equivalents: ladderlive.py --status / --arm KEY --acct NAME / --disarm KEY / --clear-halt KEY. '
             'Page updated %s.</p></body></html>' % time.strftime("%H:%M:%S"))
    return "".join(h).encode("utf-8")
