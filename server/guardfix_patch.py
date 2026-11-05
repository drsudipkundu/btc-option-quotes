"""5-Nov-2026: stop the false 'GUARD position mismatch on serverbot' emails.
The paper night bot watched the serverbot account expecting NO positions, but the live night seller (nightlive)
trades in that account. Now the guard expects exactly the live seller's open legs (contracts), so a real
mismatch is still reported. Usage: python3 guardfix_patch.py ~/deltabot"""
import sys, os
home = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(home, "nightbot.py")
s = open(p).read()
if "def live_expected(" in s:
    print("guard fix already in nightbot.py"); sys.exit(0)
old = "guard.watch(self.guard_cl, acct, {},"
if old not in s:
    print("ERROR: guard call not found in nightbot.py - nothing changed"); sys.exit(1)
func = '''
def live_expected(acct):
    """Contracts the LIVE night seller (nightlive) should hold in this account: short = negative."""
    try:
        cfg = json.load(open(os.path.join(HOME, "state", "night_live_cfg.json")))
        if str(cfg.get("acct", "")).lower() != acct or not cfg.get("armed"):
            return {}
        S = json.load(open(os.path.join(HOME, "state", "night_nlive.json")))
    except Exception:
        return {}
    exp = {}
    for l in S.get("legs", []):
        if l.get("closed"):
            continue
        n = int(round(float(l.get("qty", 0)) / 0.001))
        exp[l["sym"]] = exp.get(l["sym"], 0) + (-n if l.get("dir") == "S" else n)
    return {k: v for k, v in exp.items() if v}

class Runner:'''
s = s.replace("\nclass Runner:", func, 1)
s = s.replace(old, "guard.watch(self.guard_cl, acct, live_expected(acct),", 1)
open(p + ".bak_guard", "w").write(open(p).read())
open(p, "w").write(s)
print("guard fix applied to nightbot.py")
