# 11-Nov-2026: v15 = PAPER bot "lv15" in variantbot = v13 hyperdynamic ladder (identical gap logic, 4-hour ER) + the EXTRA CALL SPLIT
# (ladcall_v15_patch.py: extra 5x of covered, first 2x at the normal strike, the rest at the lowest strike above BTC x 1.06).
# Needs v13_patch.py applied first. Patches variants.py, control.py, ui.py, stratinfo.py, chartpage.py, ladderlive.py (KEYS only).
# Idempotent; backups *.bak_v15. The ladder shadow fleet is NOT changed: v15's ladder = v13's, so the v13 fleet already covers it.
import os, re, sys, shutil
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
def rd(n): return open(os.path.join(H, n), encoding="utf-8").read()
def wr(n, s):
    p = os.path.join(H, n)
    if not os.path.exists(p + ".bak_v15"):
        shutil.copy2(p, p + ".bak_v15")
    open(p, "w", encoding="utf-8").write(s)

s = rd("variants.py")
assert '"lv13"' in s, "v13 must be installed first"
if '"lv15"' in s:
    print("variants.py: lv15 already there")
else:
    a = '    "lv13": dict(kind="v13", label="v13"),\n'
    assert s.count(a) == 1, "variants: lv13 entry anchor"
    s = s.replace(a, a + '    "lv15": dict(kind="v13", label="v15"),\n')
    b = 'getattr(self, "key", "") == "lv13"'
    assert s.count(b) == 1, "variants: lv13 ER wrapper anchor"
    s = s.replace(b, 'getattr(self, "key", "") in ("lv13", "lv15")')
    wr("variants.py", s); print("variants.py: lv15 added")

s = rd("control.py")
m = re.search(r'NAMES = \(([^)]*)\)', s); assert m, "control: NAMES"
if '"lv15"' in m.group(1): print("control.py: lv15 already there")
else:
    s = s[:m.start()] + 'NAMES = (%s, "lv15")' % m.group(1).rstrip(", ") + s[m.end():]
    wr("control.py", s); print("control.py: lv15 added")

s = rd("ui.py")
if '"lv15": (' in s: print("ui.py: lv15 already there")
else:
    a = '    "lv13": ('
    assert s.count(a) == 1, "ui: lv13 catalogue anchor"
    s = s.replace(a, '    "lv15": ("BTC Ladder v15 (v13 + extra call split)", "Ladder exactly as v13 (4-hour ER gap 0.5 / 0.75 / 1.0 %). Call leg changed: the extra call is 5x the covered quantity (cap 0.3 BTC), only when yesterday closed at or below SMA100. The first 2x of it is sold at the normal strike (at least 5% out, delta about 0.03); the remaining 3x is sold at the lowest strike above BTC x 1.06, and skipped if there is none. Stops: each strike x 1.05, 17:20 buy-back. Backtest 2024-26: split beats all-5% (profit +37%, worst day -6,020 vs -8,235 per 1 BTC covered)."),\n' + a, 1)
    wr("ui.py", s); print("ui.py: lv15 catalogue added")

try:
    s = rd("stratinfo.py")
    if '"lv15"' in s: print("stratinfo.py: lv15 already there")
    else:
        a = '    "lv12": dict(LAD_COMMON,'
        if s.count(a) != 1:
            print("stratinfo.py: anchor not found, skipped (bot still fine)")
        else:
          s = s.replace(a, '    "lv15": dict(LAD_COMMON, title="Ladder v15 (v13 + extra call split)", kind="ladder",\n'
                         '                 strike="Ladder as v13 (4-hour ER gap 0.5 / 0.75 / 1.0 %). Covered call: delta 0.03, at least 5 % out. Extra call 5x covered (cap 0.3 BTC) if yesterday closed <= SMA100: first 2x at the same strike, the rest at the lowest strike above BTC x 1.06 (skipped if none)",\n'
                         '                 size="As v9: 0.004 / 0.002 BTC by SMA100, brake 0.28 BTC",\n'
                         '                 rules="Stops strike x 1.05 per position, buy-back 17:20 on expiry day; every sale by Smart Sell"),\n' + a, 1)
        wr("stratinfo.py", s); print("stratinfo.py: lv15 added")
except FileNotFoundError:
    print("stratinfo.py not found, skipped")

try:
    s = rd("chartpage.py")
    a = '("lv13", "v13", "v13"))'
    if '("lv15", "v13", "v15")' in s: print("chartpage.py: lv15 already there")
    elif s.count(a) == 1:
        wr("chartpage.py", s.replace(a, '("lv13", "v13", "v13"), ("lv15", "v13", "v15"))')); print("chartpage.py: lv15 lines added")
    else: print("chartpage.py: anchor not found, skipped (bot still fine)")
except FileNotFoundError:
    print("chartpage.py not found, skipped")

try:
    s = rd("ladderlive.py")
    a = 'KEYS = ("ladder", "lv10", "lv11", "lv12", "lv13")'
    if '"lv15"' in s: print("ladderlive.py: lv15 already there")
    elif s.count(a) == 1:
        wr("ladderlive.py", s.replace(a, 'KEYS = ("ladder", "lv10", "lv11", "lv12", "lv13", "lv15")')); print("ladderlive.py: lv15 key added (disarmed)")
    else: print("ladderlive.py: KEYS anchor not found, skipped")
except FileNotFoundError:
    print("ladderlive.py not found, skipped")
