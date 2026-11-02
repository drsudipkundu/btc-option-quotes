# 2-Nov-2026: v13 "hyperdynamic" ER-gap ladder as PAPER bot "lv13" inside variantbot (next to lv10 / lv11 / lv12).
# v13 = v12 mode 1 (ER bands -> gap x zone multipliers, per-lot buy-price memory, sell gap = buy gap) but the ER is read
# from 4-HOUR candles over the last 12 COMPLETED bars (48 h), thresholds 0.18 / 0.36 (matched to v12's band shares on
# Coinbase 2015-21), bands 0.5 / 0.75 / 1.0 %, re-read at every 4-hour close. Backtest: claude/v13-hyperdynamic-...
# Patches variants.py, control.py, ui.py, stratinfo.py, chartpage.py, ladderlive.py (KEYS only). Idempotent; backups *.bak_v13.
import os, re, sys, shutil
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")


def rd(n):
    return open(os.path.join(H, n), encoding="utf-8").read()


def wr(n, s):
    p = os.path.join(H, n)
    if not os.path.exists(p + ".bak_v13"):
        shutil.copy2(p, p + ".bak_v13")
    open(p, "w", encoding="utf-8").write(s)


# ---- variants.py
s = rd("variants.py")
if '"lv13"' in s:
    print("variants.py: lv13 already there")
else:
    a = 'VARIANTS = {\n'
    assert s.count(a) == 1, "variants: VARIANTS anchor"
    s = s.replace(a, a + '    "lv13": dict(kind="v13", label="v13"),\n')
    b = '\ndef make_vbot_class(bot):'
    assert s.count(b) == 1, "variants: make_vbot_class anchor"
    V13 = '''
# ---- v13 hyperdynamic (added 2-Nov-2026): v12 mode-1 logic, ER from 4-hour candles over 12 completed bars, thresholds 0.18/0.36.
V13_RES = 14400          # candle seconds (4 h, Delta UTC clock: re-reads at 05:30 / 09:30 / 13:30 / 17:30 / 21:30 / 01:30 IST)
V13_RES_NAME = "4h"
V13_N = 12               # ER lookback in bars (48 h)
V13_T1, V13_T2 = 0.18, 0.36
V13_BANDS = (0.5, 0.75, 1.0)


def v13_band_gap(er):
    if er is None:
        return V13_BANDS[1]
    return V13_BANDS[0] if er < V13_T1 else (V13_BANDS[1] if er < V13_T2 else V13_BANDS[2])


def v13_er_from_candles(cands, now, res=V13_RES, n=V13_N):
    """ER over the last n COMPLETED candles. Delta pads future candles with the last price, so only time < current bar start counts."""
    b0 = int(now // res) * res
    cd = sorted([x for x in cands if int(x["time"]) < b0], key=lambda x: x["time"])
    if len(cd) < n + 1:
        return None
    cl = [float(x["close"]) for x in cd[-(n + 1):]]
    path = sum(abs(cl[i] - cl[i - 1]) for i in range(1, n + 1))
    return (abs(cl[-1] - cl[0]) / path) if path > 0 else 0.0


_v13_prev_gaps = ERLadder.gaps


def _v13_gaps(self):
    if self.kind == "v13":
        b = [v13_band_gap(self.er) * z for z in ZM]
        return b, list(b)
    return _v13_prev_gaps(self)


ERLadder.gaps = _v13_gaps
'''
    s = s.replace(b, V13 + b)
    # wrap make_vbot_class so lv13 reads its ER from 4-hour candles (after the normal indicator refresh)
    c = '\n\ndef main():\n'
    assert s.count(c) == 1, "variants: main anchor"
    WRAP = '''

def _v13_wrap_make(orig):
    def make(bot):
        VBot = orig(bot)
        if getattr(VBot, "_v13_wrapped", False):
            return VBot
        _ri = VBot.refresh_indicators

        def refresh_indicators(self, now):
            _ri(self, now)
            if getattr(self, "key", "") == "lv13" and self.ind_ts == now:
                try:
                    cands = self.feed.candles(V13_RES_NAME, now - (V13_N + 6) * V13_RES, now)
                    er = v13_er_from_candles(cands, now)
                    if er is not None:
                        self.ladder.er = er
                except Exception as e:
                    bot.log.error("[lv13] 4h ER read failed: %s", e)
        VBot.refresh_indicators = refresh_indicators
        VBot._v13_wrapped = True
        return VBot
    return make


make_vbot_class = _v13_wrap_make(make_vbot_class)
'''
    s = s.replace(c, WRAP + c)
    wr("variants.py", s)
    print("variants.py: lv13 added")

# ---- control.py
s = rd("control.py")
m = re.search(r'NAMES = \(([^)]*)\)', s)
assert m, "control: NAMES not found"
if '"lv13"' in m.group(1):
    print("control.py: lv13 already there")
else:
    s = s[:m.start()] + 'NAMES = (%s, "lv13")' % m.group(1).rstrip(", ") + s[m.end():]
    wr("control.py", s)
    print("control.py: lv13 added")

# ---- ui.py catalogue text (+ the ER label)
s = rd("ui.py")
if '"lv13": (' in s:
    print("ui.py: lv13 already there")
else:
    a = 'CATALOG = {\n'
    assert s.count(a) == 1, "ui: CATALOG anchor"
    s = s.replace(a, a + '    "lv13": ("BTC Ladder v13 (hyperdynamic ER gap, 4-hour)", "Same as v12 mode 1, but the efficiency ratio is read from 4-hour candles over the last 12 completed bars (48 h) and re-read at every 4-hour close: ER below 0.18 gives a 0.5% gap, below 0.36 0.75%, else 1.0% (buys and sells, each lot remembers its own buy price). Reacts to a change of market within two days instead of ten."),\n')
    s = s.replace(' | ER10 %s, gap %.2f%%', ' | ER %s, gap %.2f%%')
    wr("ui.py", s)
    print("ui.py: lv13 catalogue added")

# ---- stratinfo.py (strategy details page)
try:
    s = rd("stratinfo.py")
    if '"lv13"' in s:
        print("stratinfo.py: lv13 already there")
    else:
        a = '                 rules="ER10 daily (last completed day), sell gap = buy gap"),\n})'
        assert s.count(a) == 1, "stratinfo anchor"
        s = s.replace(a, '                 rules="ER10 daily (last completed day), sell gap = buy gap"),\n'
                         '    "lv13": dict(LAD_COMMON, title="Ladder v13 hyperdynamic (ER gap 4-hour)", kind="ladder",\n'
                         '                 strike="Gap re-read at every 4-hour close: ER < 0.18 -> 0.5 %, < 0.36 -> 0.75 %, else 1.0 %; zone multipliers 1, 1, 8/3, 16/3, 28/3; each lot remembers its own buy price",\n'
                         '                 size="As v9: 0.004 / 0.002 BTC by SMA100, brake 0.28 BTC",\n'
                         '                 rules="Efficiency ratio over the last 12 completed 4-hour candles (48 h); thresholds matched to v12 band shares (Coinbase 2015-21); sell gap = buy gap"),\n})')
        wr("stratinfo.py", s)
        print("stratinfo.py: lv13 added")
except FileNotFoundError:
    print("stratinfo.py not found, skipped")

# ---- chartpage.py (chart lines)
try:
    s = rd("chartpage.py")
    a = '(("lv11", "v11", "v11"), ("lv12", "v12m1", "v12"), ("lv10", "v10", "v10"))'
    if '("lv13", "v13", "v13")' in s:
        print("chartpage.py: lv13 already there")
    elif s.count(a) == 1:
        s = s.replace(a, '(("lv11", "v11", "v11"), ("lv12", "v12m1", "v12"), ("lv10", "v10", "v10"), ("lv13", "v13", "v13"))')
        wr("chartpage.py", s)
        print("chartpage.py: lv13 lines added")
    else:
        print("chartpage.py: anchor not found, chart lines skipped (bot still fine)")
except FileNotFoundError:
    print("chartpage.py not found, skipped")

# ---- ladderlive.py: lv13 becomes a known key (disarmed by default; takes effect at the next ladderlive restart)
try:
    s = rd("ladderlive.py")
    a = 'KEYS = ("ladder", "lv10", "lv11", "lv12")'
    if '"lv13"' in s:
        print("ladderlive.py: lv13 already there")
    elif s.count(a) == 1:
        wr("ladderlive.py", s.replace(a, 'KEYS = ("ladder", "lv10", "lv11", "lv12", "lv13")'))
        print("ladderlive.py: lv13 key added (disarmed; needs a ladderlive restart to show in --status)")
    else:
        print("ladderlive.py: KEYS anchor not found, skipped")
except FileNotFoundError:
    print("ladderlive.py not found, skipped")
