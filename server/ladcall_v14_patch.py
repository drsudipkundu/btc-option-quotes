"""11-Nov-2026 (Sudip): v14 = v13 hyperdynamic ladder + EXTRA CALL SPLIT.
First `split_n` x (covered qty) of the extra call stay at the normal strike (>= 5 % out, delta ~0.03); any extra BEYOND that
('the remaining extra', for 3x, 5x ...) is sold at the lowest strike above BTC x 1.06; if no such strike or no bid it is skipped
(backtest 5x: +9,520 vs +6,968 per 1 BTC covered, worst day -6,020 vs -8,235). Only keys listed in PARAMS_BY_KEY change (lv14);
all other ladders behave exactly as before. Stops are per position (strike x 1.05), so the 6 % part has its own stop.
Idempotent, backup ladcall.py.bak_v14. Apply AFTER callmargin_patch.py (works without it too)."""
import os, re, sys, shutil
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(H, "ladcall.py"); s = open(p, encoding="utf-8").read()
if "PARAMS_BY_KEY" in s:
    print("ladcall.py already has the v14 split"); sys.exit(0)
def rep(a, b):
    global s
    if s.count(a) != 1:
        raise SystemExit("ANCHOR PROBLEM (%d hits): %r - nothing written" % (s.count(a), a[:60]))
    s = s.replace(a, b)

rep('COLS = ["time_ist"',
'''CP.update(split_n=0, otm2=1.06, x2_until=1755)   # split_n 0 = no split (v9..v13 unchanged)
# per-ladder overrides: v14 = extra 5x of covered (cap 0.3 BTC), first 2x at the normal strike, the rest >= 6 % out
PARAMS_BY_KEY = {"lv14": dict(split_n=2, otm2=1.06, xmul=5.0, xmax_btc=0.3, x2_until=1755)}
COLS = ["time_ist"''')
rep('self.P = dict(CP, **(params or {}))',
    'self.P = dict(CP, **(params if params is not None else PARAMS_BY_KEY.get(key, {})))')
rep('        # 2) a running Smart Sell job\n',
'''        # 1b) a pending second part of the extra (after a restart between the two jobs)
        if not S["job"] and S.get("x2"):
            self._start_x2(now, mark, ladder, now_ts, hm)
            changed = True
        # 2) a running Smart Sell job
''')
# extra block: split the quantity
m = re.search(r'                if o and xn >= 1:\n.*?\n(?=    # -{10,} stop button)', s, re.S)
assert m, "extra block not found"
old = m.group(0)
assert old.count("ssjob.new_job") == 1 and "_job_done(now, spot, S[\"job\"]" in old, "extra block shape"
new = '''                n2 = 0
                if P.get("split_n") and xn > int(P["split_n"] * sold):
                    n2 = xn - int(P["split_n"] * sold)
                    xn = int(P["split_n"] * sold)
                if o and xn >= 1:
                    if n2 >= 1:
                        S["x2"] = dict(n=n2, exp=J["exp"])
                    S["job"] = ssjob.new_job("x", "CE", o, xn, ch, now_ts, P["floor"],
                                             "extra x%.0f (close %.0f <= SMA100 %.0f)%s" % (P["xmul"], pc, sma, (", first %d" % xn) if n2 else ""))
                    if ssjob.run_job(S["job"], ch, now_ts, self.ex):
                        self._job_done(now, spot, S["job"], ladder, feed, sma, now_ts, hm)
        if J["key"] == "x" and S.get("x2") and not S["job"]:
            self._start_x2(now, spot, ladder, now_ts, hm)

    def _start_x2(self, now, spot, ladder, now_ts, hm):
        """second part of the extra: lowest listed strike above spot x otm2 (6 %); skipped when none / no bid / too late."""
        S, P = self.S, self.P
        x2 = S.pop("x2", None)
        if not x2:
            return
        if now_ts >= x2["exp"] or hm >= P["x2_until"]:
            self.row(now, "SKIP", "x2", "", 0, x2["n"], 0, 0, 0, "second part of the extra not started (too late)")
            return
        ch = self.chain(x2["exp"], now_ts, every=0)
        c = sorted([o for o in ch if o["delta"] > 0 and not o["ro"] and o["strike"] > spot * P["otm2"]], key=lambda o: o["strike"])
        if not c:
            self.row(now, "SKIP", "x2", "", 0, x2["n"], 0, 0, 0, "no listed strike above %.0f (BTC x %.2f)" % (spot * P["otm2"], P["otm2"]))
            self.notify("%s call extra part 2 skipped" % self.key, "no strike above BTC x %.2f" % P["otm2"])
            return
        o = c[0]
        S["job"] = ssjob.new_job("x2", "CE", o, x2["n"], ch, now_ts, P["floor"], "extra part 2 (>= %.0f%% out); delta %.3f" % ((P["otm2"] - 1) * 100, o["delta"]))
        self.log("%s call: extra part 2 started %s x%d" % (self.key, o["sym"], x2["n"]))
        if ssjob.run_job(S["job"], ch, now_ts, self.ex):
            self._job_done(now, spot, S["job"], ladder, feed=None, sma=None, now_ts=now_ts, hm=hm)

'''
s = s.replace(old, new)
shutil.copy2(p, p + ".bak_v14")
open(p, "w", encoding="utf-8").write(s)
print("ladcall.py: v14 extra split added (only lv14 uses it)")
