# Patch for ~/deltabot (29-Oct-2026): adds paper copies v4A-CG-SL and v5A-CG-SL to the night bot.
# SL rule (same as Tradetron templates 999303814 / 999303818): MA50 slope acceleration on daily candles
# (last completed day) above 0.123 -> every sell quantity of the SL copies is halved for that night.
# Old v4A-CG / v5A-CG keep running unchanged. Paper only. Idempotent: refuses to patch twice.
import sys, os, re
HOME = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
MARK = "SL_THR = 0.123"

def rd(f):
    return open(os.path.join(HOME, f), encoding="utf-8").read()

def rep(s, old, new, f, count=1):
    n = s.count(old)
    if n < 1 or (count == 1 and n != 1):
        raise SystemExit("ANCHOR PROBLEM in %s (%d hits): %r - nothing written" % (f, n, old[:70]))
    return s.replace(old, new)

out = {}
# ---------------------------------------------------------------- nightlogic.py
f = "nightlogic.py"
s = rd(f)
if MARK in s:
    print("already patched - nothing to do"); sys.exit(0)
i = s.index("MAX_JUMP = 1200.0")
j = s.index("\n", i) + 1
s = s[:j] + ('SL_THR = 0.123 # slope rule (29-Oct-2026): MA50 slope acceleration above this -> SL copies sell half size\n'
             'SL_CUT = 0.5\n'
             'LABELS = {"v4a": "V4A-CG", "v5a": "V5A-CG", "v4asl": "V4A-CG-SL", "v5asl": "V5A-CG-SL"}\n') + s[j:]
s = rep(s, "def indicators(candles, now_ts):", '''def slope_acc(C):
    """MA50 slope acceleration, as in the Tradetron SL copies. slope = (SMA50[-1]/SMA50[-6] - 1) / (daily sigma20 x sqrt 5);
    acc = slope now - slope 5 days earlier. C = completed daily closes, oldest first."""
    if len(C) < 62:
        return None

    def sma(e):
        n = len(C) - e
        return sum(C[n - 50:n]) / 50

    def sig(e):
        X = C[:len(C) - e]
        r = [math.log(X[k] / X[k - 1]) for k in range(len(X) - 20, len(X))]
        m = sum(r) / 20
        return math.sqrt(sum((x - m) ** 2 for x in r) / 19) * math.sqrt(5)
    m1, m6, m11, s1, s6 = sma(0), sma(5), sma(10), sig(0), sig(5)
    if not (m6 and m11 and s1 and s6):
        return None
    return (m1 / m6 - 1) / s1 - (m6 / m11 - 1) / s6

def indicators(candles, now_ts):''', f)
s = rep(s, 'atr=a, day=cs[-1]["time"])', 'atr=a, day=cs[-1]["time"], sl_acc=slope_acc(C))', f)
s = rep(s, 'assert variant in ("v4a", "v5a")', 'assert variant in LABELS\n        self.rule, self.lab, self.sl = variant[:3], LABELS[variant], variant.endswith("sl")', f)
s = rep(s, "    def boost_qty(self, ind):", '''    def size_base(self, ind):
        """SL copies: half size when the MA50 slope is speeding up (acc > SL_THR). Others: always the base."""
        if self.sl and ind.get("sl_acc") is not None and ind["sl_acc"] > SL_THR:
            return round(self.base * SL_CUT, 3)
        return self.base

    def boost_qty(self, ind):''', f)
s = rep(s, "base, v = self.base, self.variant", "base, v = self.size_base(ind), self.rule", f)
s = rep(s, "        base = self.base\n", "        base = self.size_base(ind)\n", f)
s = rep(s, 'if self.variant == "v4a":', 'if self.rule == "v4a":', f)
s = rep(s, 'self.variant.upper() + "-CG"', "self.lab", f)
s = rep(s, '"%s-CG ', '"%s ', f, count=0)
s = rep(s, "self.variant.upper()", "self.lab", f, count=0)
out[f] = s
# ---------------------------------------------------------------- nightbot.py
f = "nightbot.py"
s = rd(f)
s = rep(s, "IST, UTC, MIN_BID, MAX_JUMP)", "IST, UTC, MIN_BID, MAX_JUMP, SL_THR)", f)
s = rep(s, 'for v in ("v4a", "v5a")]', 'for v in ("v4a", "v5a", "v4asl", "v5asl")]', f)
s = rep(s, '        pk = make_picks(spot, ind["hv14"], ch)\n', '''        pk = make_picks(spot, ind["hv14"], ch)
        sa = ind.get("sl_acc")
        lines.append("slope accel %s -> SL copies %s (half size above %.3f)" % (
            ("%.3f" % sa) if sa is not None else "n/a", "HALF size" if (sa is not None and sa > SL_THR) else "normal size", SL_THR))
''', f)
s = rep(s, '"%s-CG', '"%s', f, count=0)
s = rep(s, "n.variant.upper()", "n.lab", f, count=0)
s = rep(s, '"v4A-CG and v5A-CG paper copies are running', '"v4A-CG, v5A-CG and slope-half v4A-CG-SL, v5A-CG-SL paper copies are running', f)
out[f] = s
# ---------------------------------------------------------------- control.py
f = "control.py"
s = rd(f)
s = rep(s, 'NAMES = ("ladder", "v4a", "v5a", "lv11", "lv12")', 'NAMES = ("ladder", "v4a", "v5a", "lv11", "lv12", "v4asl", "v5asl")', f)
out[f] = s
# ---------------------------------------------------------------- night.sh
f = "night.sh"
s = rd(f)
s = rep(s, "for v in v4a v5a;", "for v in v4a v5a v4asl v5asl;", f)
out[f] = s
# ---------------------------------------------------------------- ui.py
f = "ui.py"
s = rd(f)
s = rep(s, '    me, other = sid.upper(), ("V5A" if sid == "v4a" else "V4A")\n',
        '    import re as _re, nightlogic as _NL\n'
        '    _has = lambda subj, lab: _re.search(_re.escape(lab) + r"(?![\\w-])", subj.upper()) is not None\n'
        '    me = _NL.LABELS.get(sid, sid.upper())\n'
        '    others = [l for k, l in _NL.LABELS.items() if k != sid]\n', f)
s = rep(s, '''    return [x for x in r if "NIGHT" in x["subject"] and (me in x["subject"].upper() or other not in x["subject"].upper())]''',
        '''    return [x for x in r if "NIGHT" in x["subject"] and (_has(x["subject"], me) or not any(_has(x["subject"], o) for o in others))]''', f)
i = s.index('    "v5a": ("BTC Night Leg V5A-CG (crash guard)"')
j = s.index("\n", i) + 1
s = s[:j] + ('    "v4asl": ("BTC Night Leg V4A-CG-SL (slope half)", "V4A-CG with the slope rule: when the 50-day MA slope is speeding up (acceleration above 0.123, previous completed day) every sell quantity that night is halved. Paper copy of Tradetron template 999303814."),\n'
             '    "v5asl": ("BTC Night Leg V5A-CG-SL (slope half)", "V5A-CG with the same slope rule (half size when the 50-day MA slope acceleration is above 0.123). Paper copy of Tradetron template 999303818."),\n') + s[j:]
s = rep(s, '    for v in ("v4a", "v5a"):\n        Sx = jload(os.path.join(HOME, "state", "night_%s.json" % v)) or {}',
        '    for v in ("v4a", "v5a", "v4asl", "v5asl"):\n        Sx = jload(os.path.join(HOME, "state", "night_%s.json" % v)) or {}', f)
s = rep(s, 'name="BTC Night Leg %s-CG (crash guard)" % v.upper()',
        'name=CATALOG[v][0] if v.endswith("sl") else "BTC Night Leg %s-CG (crash guard)" % v.upper()', f)
out[f] = s
# ---------------------------------------------------------------- write (all anchors found)
for f, s in out.items():
    p = os.path.join(HOME, f)
    os.replace(p, p + ".bak10") if not os.path.exists(p + ".bak10") else None
    open(p, "w", encoding="utf-8").write(s)
    if f == "night.sh":
        os.chmod(p, 0o755)
    print("patched", f)
