# Adds the LIVE night card "nlive" to control.py / ui.py / night.sh (idempotent; backups *.bak12). No orders here.
import sys, os, json
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
def rd(f): return open(os.path.join(H, f), encoding="utf-8").read()
def wr(f, s):
    p = os.path.join(H, f)
    if not os.path.exists(p + ".bak12"):
        open(p + ".bak12", "w", encoding="utf-8").write(rd(f))
    open(p, "w", encoding="utf-8").write(s); print("patched", f)
def rep(s, a, b, f):
    if b in s: return s
    assert s.count(a) == 1, "anchor problem in %s: %r" % (f, a[:60]); return s.replace(a, b)
s = rd("control.py")
if '"nlive"' not in s:
    s = rep(s, '"v4asl", "v5asl")', '"v4asl", "v5asl", "nlive")', "control.py"); wr("control.py", s)
s = rd("ui.py")
if '"nlive"' not in s:
    s = rep(s, '    for v in ("v4a", "v5a", "v4asl", "v5asl"):\n        Sx = jload(', '    for v in ("v4a", "v5a", "v4asl", "v5asl", "nlive"):\n        Sx = jload(', "ui.py")
    s = rep(s, 'name=CATALOG[v][0] if v.endswith("sl") else', 'name=CATALOG[v][0] if (v.endswith("sl") or v == "nlive") else', "ui.py")
    i = s.index('    "v5asl": ('); j = s.index("\n", i) + 1
    s = s[:j] + '    "nlive": ("BTC Night Leg V4A-CG-SL LIVE MONEY (server)", "REAL ORDERS on the Delta sub-account in state/night_live_cfg.json, only while armed. Rules of V4A-CG-SL; smart seller: 80% walk-away, polite mid offer, 3 retries, up to 4 further strikes; size guard; position check halts on any mismatch. Pause = no new sales, Exit = buy back everything."),\n' + s[j:]
    s = rep(s, '    me = _NL.LABELS.get(sid, sid.upper())', '    me = _NL.LABELS.get(sid, sid.upper())\n    if sid == "nlive": me = "NLIVE"', "ui.py")
    wr("ui.py", s)
s = rd("night.sh")
if "nightlive" not in s:
    s = rep(s, '  *) echo "Words:', '  live) ./venv/bin/python nightlive.py --status; sudo systemctl is-active nightlive; tail -n 15 logs/nightlive.log ;;\n  *) echo "Words:', "night.sh")
    wr("night.sh", s)

s = rd("ui.py")
a1 = """        h.append('<div class="row pp"><div class="t">%s</div><div style="margin-top:6px"><span class="badge paper">PAPER &middot; AUTO</span><span class="badge %s">%s</span>'
                 '<span class="m">Delta India (own server)</span></div>' % (E(s["name"]), sc, E(stt)))"""
b1 = """        _hd = ('<div class="row ll"><div class="t">%s</div><div style="margin-top:6px"><span class="badge live">LIVE MONEY &middot; AUTO</span><span class="badge %s">%s</span>' if c["mode"] == "live" else '<div class="row pp"><div class="t">%s</div><div style="margin-top:6px"><span class="badge paper">PAPER &middot; AUTO</span><span class="badge %s">%s</span>')
        h.append((_hd + '<span class="m">Delta India (own server)</span></div>') % (E(s["name"]), sc, E(stt)))"""
if "LIVE MONEY &middot; AUTO" not in s:
    s = rep(s, a1, b1, "ui.py")
    s = rep(s, 'svc=svc("nightbot"), c=ctl[v]', 'svc=svc("nightlive" if v == "nlive" else "nightbot"), c=ctl[v]', "ui.py")
    wr("ui.py", s)
# Live card shows on the Live tab
cp = os.path.join(H, "state", "control.json")
try: d = json.load(open(cp))
except Exception: d = {}
d.setdefault("nlive", {}).update(mode="live", deployed=True)
d["nlive"].setdefault("state", "running")
json.dump(d, open(cp + ".tmp", "w")); os.replace(cp + ".tmp", cp); print("control: nlive mode live")
