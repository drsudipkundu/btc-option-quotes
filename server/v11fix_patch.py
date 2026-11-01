# 1-Nov-2026: server v11 must change ONLY the zone-1 gap when choppy (Sudip 21-Oct; Tradetron v11 999231898 does the same):
# ER10 < 0.2 at cycle start -> zone 1 = 0.5 %, zones 2-5 stay 0.75 / 2 / 4 / 7 %. Before this fix the server scaled
# every zone by 0.5/0.75. Idempotent; backup variants.py.bak_v11.
import sys, os
HOME = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(HOME, "variants.py")
s = open(p, encoding="utf-8").read()
if "v11 zone-1 only" in s:
    print("v11 fix already in"); sys.exit(0)
a = '''        if self.kind == "v11":
            b = [self.base * z for z in ZM]
            return b, list(b)
'''
if s.count(a) != 1:
    raise SystemExit("ANCHOR PROBLEM - nothing written")
s = s.replace(a, '''        if self.kind == "v11":  # v11 zone-1 only: the choppy switch changes zone 1, zones 2-5 stay as v9
            b = [self.base] + [0.75 * z for z in ZM[1:]]
            return b, list(b)
''')
if not os.path.exists(p + ".bak_v11"):
    os.replace(p, p + ".bak_v11")
open(p, "w", encoding="utf-8").write(s)
print("v11 zone-1-only fix applied")
