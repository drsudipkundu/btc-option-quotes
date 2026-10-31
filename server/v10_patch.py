# 31-Oct-2026: adds paper ladder "lv10" (nested ladder v10 = 4 ladders x Z1+Z2, x2 lots from ladder 3) to the variant bot.
# Patches ~/deltabot/variants.py, control.py, ui.py (catalogue text) and chartpage.py (chart lines). Idempotent; backups *.bak_v10.
import os, re, sys, shutil
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")


def rd(n):
    return open(os.path.join(H, n), encoding="utf-8").read()


def wr(n, s):
    p = os.path.join(H, n)
    if not os.path.exists(p + ".bak_v10"):
        shutil.copy2(p, p + ".bak_v10")
    open(p, "w", encoding="utf-8").write(s)


# ---- variants.py
s = rd("variants.py")
if '"lv10"' not in s:
    a = 'VARIANTS = {\n'
    assert s.count(a) == 1, "variants: VARIANTS anchor"
    s = s.replace(a, a + '    "lv10": dict(kind="v10", label="v10"),\n')
    b = '\ndef make_vbot_class(bot):'
    assert s.count(b) == 1, "variants: make_vbot_class anchor"
    V10 = '''
# ---- v10 nested ladder (added 31-Oct-2026). Same LIFO engine; 8 zones = 4 ladders x (Z1 + Z2).
# Ladder k starts at 0.6032^(k-1) of the cycle entry, so its 0.75% steps shrink to 0.4524 / 0.2729 / 0.1646 % of entry.
# Lots: zones 1-4 0.004 above SMA100 / 0.002 below; zones 5-8 double (0.008 / 0.004). Entry 0.002. Cap 0.40 BTC.
# No buys below 13.24% of entry (stop depth = 4 ladders, about -87%).
V10_GAPS = [0.75, 0.75, 0.4524, 0.4524, 0.2729, 0.2729, 0.1646, 0.1646]
V10_FLOORS = [73.54, 60.32, 44.36, 36.38, 26.76, 21.95, 16.14, 13.24]
V10_CAP_BTC = 0.40


def v10_zone(pct):
    for i, f in enumerate(V10_FLOORS):
        if pct > f:
            return i + 1
    return 9


_er_init, _er_gaps, _er_nlb, _er_sell, _er_size = (ERLadder.__init__, ERLadder.gaps, ERLadder.next_level_below,
                                                   ERLadder.sell_price, ERLadder.lot_size_for)


def _v10_init(self, kind, scale=1.0):
    _er_init(self, kind, scale=scale)
    if kind == "v10":
        self.brake = max(1, int(round(V10_CAP_BTC / BTC_PER_CONTRACT * scale)))


def _v10_gaps(self):
    if self.kind == "v10":
        return list(V10_GAPS), list(V10_GAPS)
    return _er_gaps(self)


def _v10_nlb(self, level):
    if self.kind != "v10":
        return _er_nlb(self, level)
    z = v10_zone(level / self.entry * 100.0)
    if z > 8:
        return 0.0
    nxt = level - self.entry * V10_GAPS[z - 1] / 100.0
    for f in V10_FLOORS:
        fl = self.entry * f / 100.0
        if level > fl + 1e-9 and nxt < fl - 1e-9:
            nxt = fl
            break
    if nxt < self.entry * V10_FLOORS[-1] / 100.0 - 1e-6:
        return 0.0
    return nxt


def _v10_sell(self, lot):
    if self.kind != "v10":
        return _er_sell(self, lot)
    z = min(8, v10_zone(lot["level"] / self.entry * 100.0))
    return lot["buy_price"] + self.entry * V10_GAPS[z - 1] / 100.0


def _v10_size(self, level, sma):
    c = _er_size(self, level, sma)
    if self.kind == "v10" and self.entry > 0 and level > 0 and v10_zone(level / self.entry * 100.0) >= 5:
        c *= 2
    return c


ERLadder.__init__, ERLadder.gaps, ERLadder.next_level_below, ERLadder.sell_price, ERLadder.lot_size_for = (
    _v10_init, _v10_gaps, _v10_nlb, _v10_sell, _v10_size)

'''
    s = s.replace(b, V10 + b)
    wr("variants.py", s)
    print("variants.py: lv10 added")
else:
    print("variants.py: lv10 already there")

# ---- control.py
s = rd("control.py")
m = re.search(r'NAMES = \(([^)]*)\)', s)
assert m, "control: NAMES not found"
if '"lv10"' not in m.group(1):
    s = s[:m.start()] + 'NAMES = (%s, "lv10")' % m.group(1).rstrip(", ") + s[m.end():]
    wr("control.py", s)
    print("control.py: lv10 added")
else:
    print("control.py: lv10 already there")

# ---- ui.py catalogue text
s = rd("ui.py")
if '"lv10": (' not in s:
    a = 'CATALOG = {\n'
    assert s.count(a) == 1, "ui: CATALOG anchor"
    s = s.replace(a, a + '    "lv10": ("BTC Ladder v10 (nested, 4 ladders)", "Nested ladder: four Zone1+Zone2 ladders stacked down to 13% of entry. Each new ladder starts at 60.32% of the one above, so steps are 0.75 / 0.45 / 0.27 / 0.16% of entry; ladders 3-4 buy double lots. Same entry filter, LIFO sells and SMA100 lot sizing as v9; cap 0.40 BTC."),\n')
    wr("ui.py", s)
    print("ui.py: lv10 catalogue added")
else:
    print("ui.py: lv10 already there")

# ---- chartpage.py (optional: chart lines)
try:
    s = rd("chartpage.py")
    a = '(("lv11", "v11", "v11"), ("lv12", "v12m1", "v12"))'
    if '("lv10", "v10", "v10")' in s:
        print("chartpage.py: lv10 already there")
    elif s.count(a) == 1:
        s = s.replace(a, '(("lv11", "v11", "v11"), ("lv12", "v12m1", "v12"), ("lv10", "v10", "v10"))')
        wr("chartpage.py", s)
        print("chartpage.py: lv10 lines added")
    else:
        print("chartpage.py: anchor not found, chart lines skipped (bot still fine)")
except Exception as e:
    print("chartpage.py skipped:", e)
