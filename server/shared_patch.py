"""6-Nov-2026: let a live ladder (e.g. lv13) share the serverbot account with the live night seller.
ladderlive.py: new cfg flag "shared" (auto-set when --acct serverbot). Shared => (1) call leg forced OFF,
(2) option positions are NOT checked (they belong to the night seller), BTCUSD futures still must equal the ladder,
(3) ladder writes state/ladder_expected_<acct>.json each minute so the guard/night watcher expects those futures,
(4) --arm refuses a second armed ladder on the same account, (5) --check accepts --acct NAME.
guard.py: open-position limit counts options only (not BTCUSD futures). nightbot.py: live_expected() adds the ladder's BTCUSD contracts. All-or-nothing, idempotent, backups *.bak_shared.
Usage: python3 shared_patch.py ~/deltabot   (no restart done here)"""
import os, sys
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
NEW = {}
def rd(n): return open(os.path.join(H, n), encoding="utf-8").read()
def rep(name, s, a, b, cnt=1):
    if s.count(a) != cnt:
        raise SystemExit("ANCHOR PROBLEM in %s (%d hits): %r - nothing written" % (name, s.count(a), a[:70]))
    return s.replace(a, b)

s = rd("ladderlive.py")
if "shared_patch" in s:
    print("ladderlive.py: already patched")
else:
    s = rep("ladderlive.py", s, 'max_hold_btc=None, halt=None)', 'max_hold_btc=None, halt=None, shared=False)')
    s = rep("ladderlive.py", s, '    return {k: dict(DEF, **d.get(k, {})) for k in KEYS}\n',
        '    out = {k: dict(DEF, **d.get(k, {})) for k in KEYS}\n'
        '    for v in out.values():  # shared_patch: on a shared account the call leg is never on\n'
        '        if v.get("shared"):\n            v["calls"] = False\n    return out\n')
    s = rep("ladderlive.py", s,
        '            exp = self.calls.expected_positions() if self.cfg.get("calls") else {}\n',
        '            try:  # shared_patch: tell the guard which BTCUSD contracts the ladder owns\n'
        '                json.dump({"acct": self.cfg["acct"], "key": self.live_key, SYM: real, "ts": time.time()},\n'
        '                          open(os.path.join(HOME, "state", "ladder_expected_%s.json" % self.cfg["acct"]), "w"))\n'
        '            except Exception:\n                pass\n'
        '            if self.cfg.get("shared"):\n                return True  # options belong to the night seller\n'
        '            exp = self.calls.expected_positions() if self.cfg.get("calls") else {}\n')
    s = rep("ladderlive.py", s,
        '        print(put(key, armed=True, acct=acct, halt=None))\n',
        '        c0 = load_cfg()\n'
        '        for k2, v2 in c0.items():\n'
        '            if k2 != key and v2["armed"] and v2["acct"] == acct:\n'
        '                raise SystemExit("REFUSED: %s is already armed on account %s" % (k2, acct))\n'
        '        sh = acct == "serverbot"\n'
        '        print(put(key, armed=True, acct=acct, halt=None, shared=sh, **({"calls": False} if sh else {})))\n')
    s = rep("ladderlive.py", s,
        '        cl = client_for(load_cfg()[key]["acct"])\n        print("account:", cl.profile())',
        '        cl = client_for(a[a.index("--acct") + 1] if "--acct" in a else load_cfg()[key]["acct"])\n        print("account:", cl.profile())')
    s = s.replace('"""', '"""', 1)
    s += "\n# shared_patch applied 6-Nov-2026\n"
    NEW["ladderlive.py"] = s

n = rd("nightbot.py") if os.path.exists(os.path.join(H, "nightbot.py")) else None
if n is None:
    print("nightbot.py not found, skipped")
elif "ladder_expected_" in n:
    print("nightbot.py: already patched")
elif "def live_expected(acct):" not in n:
    raise SystemExit("nightbot.py has no live_expected - run guardfix_patch first; nothing written")
else:
    n = rep("nightbot.py", n, '    return {k: v for k, v in exp.items() if v}\n',
        '    try:  # shared_patch: BTCUSD futures owned by a live ladder on this account\n'
        '        L = json.load(open(os.path.join(HOME, "state", "ladder_expected_%s.json" % acct)))\n'
        '        if __import__("time").time() - L.get("ts", 0) < 600 and L.get("BTCUSD"):\n'
        '            exp["BTCUSD"] = int(L["BTCUSD"])\n'
        '    except Exception:\n        pass\n'
        '    return {k: v for k, v in exp.items() if v}\n')
    NEW["nightbot.py"] = n

g = rd("guard.py") if os.path.exists(os.path.join(H, "guard.py")) else None
if g is None:
    print("guard.py not found, skipped")
elif 'prefixes=("C-BTC", "P-BTC")' in g:
    print("guard.py: already patched")
else:  # the ladder's BTCUSD futures have their own brake/limits in ladderlive; the guard's open limit is for option legs
    g = rep("guard.py", g, 'def open_btc(positions, prefixes=("BTC", "C-BTC", "P-BTC")):',
            'def open_btc(positions, prefixes=("C-BTC", "P-BTC")):  # shared_patch: options only, BTCUSD futures belong to the ladder')
    NEW["guard.py"] = g

for name, txt in NEW.items():
    p = os.path.join(H, name)
    open(p + ".bak_shared", "w", encoding="utf-8").write(open(p, encoding="utf-8").read())
    open(p, "w", encoding="utf-8").write(txt)
    print("patched", name)
