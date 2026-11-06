"""6-Nov-2026: ladderlive.py - a ladder may START (first arm, no saved live state) only on a FLAT account:
no BTCUSD position, no option position, no open orders (unless the account is 'shared', where only BTCUSD must be 0
and option positions belong to the night seller). Protects ladder9 while Tradetron v9 still trades there: arming lv13
early would otherwise halt at once and cancel ALL open orders in the account (v9's too). Idempotent; backup *.bak_flat."""
import os, sys, shutil
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(H, "ladderlive.py"); s = open(p, encoding="utf-8").read()
if "flatstart_patch" in s:
    print("ladderlive.py: flat-start check already there"); sys.exit(0)
a = ('            if c["armed"] and k not in bots:\n'
     '                try:\n')
if s.count(a) != 1:
    raise SystemExit("ANCHOR PROBLEM (%d hits) - nothing written" % s.count(a))
b = a + ('                    if not os.path.exists(os.path.join(HOME, "state", "live_%s_state.json" % k)):  # flatstart_patch\n'
         '                        _cl = client_for(c["acct"]); _pos = {x: v for x, v in _cl.positions().items() if int(round(v))}\n'
         '                        _bad = {x: v for x, v in _pos.items() if x == SYM or not c.get("shared")}\n'
         '                        _oo = [] if c.get("shared") else _cl.open_orders()\n'
         '                        if _bad or _oo:\n'
         '                            raise RuntimeError("account %s is not flat (positions %s, open orders %d) - first start refused, nothing cancelled" % (c["acct"], _bad, len(_oo)))\n')
s = s.replace(a, b)
shutil.copy2(p, p + ".bak_flat"); open(p, "w", encoding="utf-8").write(s)
print("ladderlive.py: flat-start check added")
