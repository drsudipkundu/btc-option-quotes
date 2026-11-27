#!/usr/bin/env python3
"""self-test for flagrank.py: runs in a temporary folder, touches nothing real."""
import csv, datetime as dt, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flagrank as F

n = 0
def ok(c, msg):
    global n
    n += 1
    if not c:
        print("FAILED:", msg); sys.exit(1)

T = tempfile.mkdtemp(); os.makedirs(os.path.join(T, "state")); os.makedirs(os.path.join(T, "logs"))
d0 = dt.date(2026, 8, 1)
days = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(101)]      # 100 past nights + the test night
last = days[-1]
def write(name, vals):
    with open(os.path.join(T, "state", name), "w", newline="") as fh:
        w = csv.writer(fh)
        for d, v in zip(days, vals): w.writerow([d, v, "delta", "X"])
def state(flags):
    json.dump({"night": last, "flags_night": dict(night=last, **flags)}, open(os.path.join(T, "state", "night_nlive.json"), "w"))
def run():
    try: os.remove(os.path.join(T, "logs", "flagrank.csv"))
    except OSError: pass
    F.main(T)
    return {r["night"]: r for r in csv.DictReader(open(os.path.join(T, "logs", "flagrank.csv")))}

past = [i + 1 for i in range(100)]                      # 1..100
# 1) premium rank 0.98 (top 5 %), P flag on, live 1.5 -> rule 1 gives 1.0
write("prem_hist.csv", past + [98.5]); write("iv_hist.csv", past + [50.5]); state(dict(P=True, V=False, R=False, mult=1.5))
r = run()[last]
ok(abs(float(r["prem_rank"]) - 0.98) < 1e-9, "premium rank 0.98, got %s" % r["prem_rank"])
ok(abs(float(r["iv_rank"]) - 0.50) < 1e-9, "iv rank 0.50")
ok(r["flags_from"] == "live" and r["live_mult"] == "1.5", "live flags read")
ok(r["rule1_mult"] == "1.0" and r["rule2_mult"] == "1.5" and r["rule12_mult"] == "1.0" and r["changed"] == "1", "rule 1 removes the extra size")
# 2) premium rank 0.93 (flag on, below 95 %) -> nothing changes
write("prem_hist.csv", past + [93.5]); r = run()[last]
ok(r["rule1_mult"] == "1.5" and r["changed"] == "0", "premium 93 %: unchanged")
# 3) no flag, volatility rank 0.75 -> rule 2 gives 1.0 instead of 0.5
write("prem_hist.csv", past + [40.5]); write("iv_hist.csv", past + [75.5]); state(dict(P=False, V=False, R=False, mult=0.5))
r = run()[last]
ok(r["live_mult"] == "0.5" and r["rule2_mult"] == "1.0" and r["rule1_mult"] == "0.5" and r["rule12_mult"] == "1.0", "rule 2 half step")
# 4) no flag, volatility rank 0.60 -> unchanged; rank exactly 0.80 is a flag night, not the half step
write("iv_hist.csv", past + [60.5]); r = run()[last]
ok(r["rule2_mult"] == "0.5" and r["changed"] == "0", "volatility 60 %: unchanged")
write("iv_hist.csv", past + [80.5]); state(dict(P=False, V=True, R=False, mult=1.5)); r = run()[last]
ok(r["rule2_mult"] == "1.5" and r["changed"] == "0", "volatility flag on: rule 2 not used")
# 5) RSI-only flag with volatility 75 %: flag on, so no half step
write("iv_hist.csv", past + [75.5]); state(dict(P=False, V=False, R=True, mult=1.5)); r = run()[last]
ok(r["rule2_mult"] == "1.5" and r["R"] == "1", "RSI flag night keeps 1.5")
# 6) fewer than 60 past nights -> no rank, no line
ok(F.rank({d: 1.0 for d in days[:30]}, days[29]) == (None, 29), "too few nights -> no rank")
# 7) older nights (no saved flags) are logged from ranks only, RSI blank; a second run adds nothing
R = run(); old = R[days[80]]
ok(old["flags_from"] == "rank-only" and old["R"] == "", "older night logged from ranks only")
ok(len(R) == 41, "41 nights have 60+ past nights, got %d" % len(R))
ok(F.main(T) == 0, "second run adds nothing")
# 8) a rank-only line is upgraded when live flags appear; a live line is never overwritten
state(dict(P=False, V=False, R=False, mult=0.5)); write("iv_hist.csv", past + [75.5]); R1 = run()
json.dump({"flags_night": dict(night=last, P=True, V=True, R=True, mult=1.5)}, open(os.path.join(T, "state", "night_nlive.json"), "w"))
F.main(T); R2 = {r["night"]: r for r in csv.DictReader(open(os.path.join(T, "logs", "flagrank.csv")))}
ok(R2[last]["live_mult"] == "0.5", "a line with live flags is kept as first written")
# 9) the script never writes into state/
before = sorted(os.listdir(os.path.join(T, "state"))); F.main(T); ok(sorted(os.listdir(os.path.join(T, "state"))) == before, "state folder untouched")
# 10) missing files do not crash
E = tempfile.mkdtemp(); ok(F.main(E) == 0, "empty folder: no crash, nothing added")
print("selftest_flagrank: %d checks PASSED" % n)
