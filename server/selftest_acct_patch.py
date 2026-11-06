# 6-Nov-2026: ladderlive.py --selftest KEY --acct NAME --yes (before: it always used the key's saved account = ladder9, the Tradetron v9 account).
# With no --acct on a self-test it now REFUSES. Idempotent; backup ladderlive.py.bak_stacct.
import os, sys, shutil
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(H, "ladderlive.py"); s = open(p, encoding="utf-8").read()
if "bak_stacct_done" in s:
    print("already patched"); sys.exit(0)
a = '        cl = client_for(load_cfg()[key]["acct"])\n        t = cl.ticker(SYM)\n'
if s.count(a) != 1:
    raise SystemExit("ANCHOR PROBLEM (%d hits) - nothing written" % s.count(a))
b = ('        if "--acct" not in a:\n            raise SystemExit("REFUSED: add --acct NAME (e.g. --acct serverbot) so the test order cannot go to the wrong account")\n'
     '        cl = client_for(a[a.index("--acct") + 1])\n        t = cl.ticker(SYM)\n')
s = s.replace(a, b) + "\n# bak_stacct_done\n"
shutil.copy2(p, p + ".bak_stacct"); open(p, "w", encoding="utf-8").write(s); print("selftest now needs --acct")
