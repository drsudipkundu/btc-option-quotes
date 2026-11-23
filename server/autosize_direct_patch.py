"""23-Nov-2026 (Sudip): 'Adjust Base directly to available balance not stepped up'.
autosize raise: straight to the allowed base (balance / safe per 0.01, rounded down, max 0.30), every night,
instead of +0.01 at most once per 7 days. Cuts were already immediate. Big base unchanged (already direct)."""
import os, sys, time
H = os.path.expanduser("~/deltabot"); F = os.path.join(H, "autosize.py")
s = open(F).read()
OLD = ('    elif live_base < max_base - 1e-9 and allowed > live_base + 1e-9 and now_ts - last_change >= STEP_DAYS * 86400:\n'
       '        out.update(action="raise", base=round(min(allowed, live_base + STEP_UP), 2))\n')
NEW = ('    elif allowed > live_base + 1e-9:   # 23-Nov-2026 (Sudip): raise straight to the allowed base, no weekly step\n'
       '        out.update(action="raise", base=round(allowed, 2))\n')
if NEW in s:
    print("already patched")
else:
    assert OLD in s, "raise line not found - nothing changed"
    s = s.replace(OLD, NEW).replace("raise +0.01 BTC at most once per 7 days, up to the max base.",
                                    "raise straight to the allowed base each night, up to the max base (23-Nov-2026).")
    open(F + ".bak1123", "w").write(open(F).read()); open(F, "w").write(s); print("patched")
sys.path.insert(0, H); os.chdir(H)
import importlib, autosize as A; importlib.reload(A)
now = time.time(); st = dict(max_base=0.30, last_set=0.11, last_change_ts=now)
t = [(A.decide(8555.0, 515.3, 0.11, True, st, now), "raise", 0.16),          # 2 L added -> straight to 0.16 the same day
     (A.decide(6200.0, 515.3, 0.16, True, dict(st, last_set=0.16), now), "cut", 0.12),
     (A.decide(20000.0, 515.3, 0.16, True, dict(st, last_set=0.16), now), "raise", 0.30),   # ceiling holds
     (A.decide(8555.0, 515.3, 0.16, True, dict(st, last_set=0.16), now), "none", 0.16)]
ok = True
for d, act, base in t:
    good = d["action"] == act and abs(d["base"] - base) < 1e-9
    ok &= good; print("  test", act, base, "->", d["action"], d["base"], "OK" if good else "FAIL")
if not ok:
    open(F, "w").write(open(F + ".bak1123").read()); print("SELF-TEST FAILED - restored the old file"); sys.exit(1)
print("SELF-TEST OK")
