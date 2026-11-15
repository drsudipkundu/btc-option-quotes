#!/usr/bin/env python3
"""v5live_patch (15-Nov-2026). Run in ~/deltabot. Behaviour-neutral until state/night_live_cfg.json gets rule=v5asl.
 1. nightlive.py : the live seller reads its rules from the config ('rule': v4asl default, or v5asl); new option --rule (refused while a
                   night position is open). Strike jump stays OFF for live money.
 2. nightlogic.py: new PAPER copy 'v5aslj' = V5A-CG-SL + strike jump of the opposite leg (BTC half-way from the sale price to the trend
                   strike -> buy back the opposite leg if still open, sell a new one at the usual distance from the current price; once a
                   night, not in the last 2 hours).
 3. nightbot.py / control.py / ui.py / night.sh: the new paper copy is run, listed and shown. All existing copies keep running unchanged.
Every edit must match exactly once, otherwise NOTHING is written. Backups: <file>.bak1115v5"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
JUMP = '''    def _jump(self, now, spot, ch, ind):
        """paper strike jump (copies whose name ends with j): when BTC is half-way from the price at the sale to the trend strike,
        buy back the opposite ('extra') leg if still open and sell a new opposite leg at the usual distance from the current price."""
        S = self.S
        if "extra" not in S["fired"] or "jump" in S["fired"] or not S.get("exp"):
            return False
        t = [l for l in self.open_legs() if l["set"] == "trend" and l["dir"] == "S"]
        ex = [l for l in S["legs"] if l["set"] == "extra" and l["dir"] == "S"]
        if not t or not ex:
            return False
        if S.get("jump_ref_night") != S["night"]:          # price at the first tick after the sale
            S["jump_ref_night"], S["jump_ref_spot"] = S["night"], spot
            return True
        if now.timestamp() > S["exp"] - 7200:
            return False
        m = t[0]
        half = (S["jump_ref_spot"] + m["strike"]) / 2.0
        if not ((spot <= half) if m["side"] == "PE" else (spot >= half)):
            return False
        opp = "CE" if m["side"] == "PE" else "PE"
        pk = make_picks(spot, ind["hv14"], ch, S.get("full", []))
        strike = pk["%s_%s" % (opp.lower(), "m" if ind["hv14"] > MOVED_HV else "n")]
        S["fired"].append("jump")
        o = find(ch, opp, strike) if strike not in (0, 9999999) else None
        if not o or o["bid"] < MIN_BID or strike == ex[-1]["strike"]:
            self.row(now, "JUMP-SKIP", None, 0, 0, 0.0, "half-way reached at %.1f, no better strike" % spot)
            return True
        for l in ex:
            if not l["closed"]:
                self._close(now, spot, l, find(ch, l["side"], l["strike"]), "JUMP")
        self._open(now, spot, "extra2", "extra", opp, o, ex[0]["qty"], "S", "strike jump at spot %.1f" % spot)
        return True

'''
EDITS = {
 "nightlogic.py": [
  ('"v5asl": "V5A-CG-SL"}', '"v5asl": "V5A-CG-SL", "v5aslj": "V5A-CG-SL-J"}'),
  ('self.rule, self.lab, self.sl = variant[:3], LABELS[variant], variant.endswith("sl")',
   'self.rule, self.lab, self.sl = variant[:3], LABELS[variant], "sl" in variant[3:]\n        self.jump = variant.endswith("j")'),
  ('        # entries\n        if 2330 <= hm <= 2358 and ind and not stopped:\n            changed |= self._entries(now, spot, ch, ind, today)\n',
   '        # entries\n        if 2330 <= hm <= 2358 and ind and not stopped:\n            changed |= self._entries(now, spot, ch, ind, today)\n'
   '        # strike jump of the opposite leg - paper copies whose name ends with j (15-Nov-2026)\n'
   '        if getattr(self, "jump", False) and ind and self.open_legs():\n            changed |= self._jump(now, spot, ch, ind)\n'),
  ('    # ---- what the rules want tonight\n', JUMP + '    # ---- what the rules want tonight\n'),
 ],
 "nightlive.py": [
  ('DEF = dict(armed=False, acct="serverbot", base=0.02, client="live",', 'DEF = dict(armed=False, acct="serverbot", base=0.02, client="live", rule="v4asl",'),
  ('        Night.__init__(self, "v4asl", base, HOME, notify=notify, log=logf)\n        self.lab = "NLIVE V4ASL"\n',
   '        rule = cfg().get("rule", "v4asl")\n        if rule not in ("v4asl", "v5asl"):\n            rule = "v4asl"\n'
   '        Night.__init__(self, rule, base, HOME, notify=notify, log=logf)\n'
   '        self.jump = False                      # strike jump is paper-only for now (15-Nov-2026)\n        self.lab = "NLIVE " + rule.upper()\n'),
  ('    ap.add_argument("--client", choices=("live", "paper"))\n    a = ap.parse_args()\n',
   '    ap.add_argument("--client", choices=("live", "paper"))\n    ap.add_argument("--rule", choices=("v4asl", "v5asl"))\n    a = ap.parse_args()\n'
   '    if a.rule:\n        try:\n            d_ = json.load(open(os.path.join(HOME, "state", "night_%s.json" % SID)))\n'
   '            busy = any(not l.get("closed") for l in d_.get("legs", []))\n        except Exception:\n            busy = False\n'
   '        if busy:\n            print("REFUSED: a night position is open - change the rule after it is closed"); return\n'
   '        print("rule:", put_cfg(rule=a.rule), "(now restart: sudo systemctl restart nightlive)"); return\n'),
  ('"account %s, base %.3f BTC, client %s, armed %s" % (c0["acct"], c0["base"], c0["client"], c0["armed"]))',
   '"account %s, base %.3f BTC, client %s, armed %s, rules %s" % (c0["acct"], c0["base"], c0["client"], c0["armed"], c0.get("rule", "v4asl")))'),
 ],
 "nightbot.py": [('for v in ("v4a", "v5a", "v4asl", "v5asl")]', 'for v in ("v4a", "v5a", "v4asl", "v5asl", "v5aslj")]')],
 "control.py": [('"v4asl", "v5asl", "nlive",', '"v4asl", "v5asl", "v5aslj", "nlive",')],
 "ui.py": [
  ('    for v in ("v4a", "v5a", "v4asl", "v5asl", "nlive"):', '    for v in ("v4a", "v5a", "v4asl", "v5asl", "v5aslj", "nlive"):'),
  ('    "nlive": ("BTC Night Leg V4A-CG-SL LIVE MONEY (server)"',
   '    "v5aslj": ("BTC Night Leg V5A-CG-SL-J (slope half + strike jump)", "V5A-CG-SL plus the strike jump: when BTC is half-way from the sale price to the trend strike, the opposite leg is bought back (if still open) and sold again at the usual distance from the current price. Paper only, added 15-Nov-2026."),\n'
   '    "nlive": ("BTC Night Leg LIVE MONEY (server; rules V4A-CG-SL or V5A-CG-SL as set)"'),
 ],
 "night.sh": [('for v in v4a v5a v4asl v5asl; do', 'for v in v4a v5a v4asl v5asl v5aslj; do')],
}
def main():
    new = {}
    for f, eds in EDITS.items():
        p = os.path.join(H, f); s = open(p).read()
        if "v5aslj" in s and f != "nightlive.py" or (f == "nightlive.py" and 'rule="v4asl"' in s):
            print("already patched:", f); continue
        for a, b in eds:
            if s.count(a) != 1:
                print("ABORT - anchor found %d times in %s: %r" % (s.count(a), f, a[:70])); sys.exit(1)
            s = s.replace(a, b)
        new[p] = s
    for p, s in new.items():
        shutil.copy2(p, p + ".bak1115v5"); open(p, "w").write(s); print("patched", os.path.basename(p))
    print("OK")
if __name__ == "__main__": main()
