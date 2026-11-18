"""offline self-test of flagpaper_patch: paper copies v5aslf (any flag x1.5) and v5aslh (any flag x1.5, no flag x0.5).
No network, no orders."""
import os, sys, csv, datetime as dt, tempfile
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot")); sys.path.insert(0, H)
import nightlogic as NL, nightbot as NB
IST = NL.IST; exp = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc).timestamp()
def chain(spot):
    out = []
    for k in range(60000, 100001, 200):
        for typ in ("PE", "CE"):
            d = abs(k - spot) / spot
            px = max(0.5, 3000 * max(0.0, 0.06 - d)) if ((typ == "PE" and k < spot) or (typ == "CE" and k > spot)) else 3000.0
            out.append(dict(sym="%s-BTC-%d-191126" % ("P" if typ == "PE" else "C", k), typ=typ, strike=float(k), exp=exp, bid=px, ask=px * 1.05 + 0.5, mark=px * 1.02, iv=0.30, oi=0.0, ro=False))
    return out
t0 = dt.datetime(2026, 11, 18, 23, 31, tzinfo=IST)
LOW, HIGH = [0.0001 * i for i in range(1, 121)], [1.0 + 0.01 * i for i in range(120)]       # tonight above all / below all
def run(variant, prem, iv, rsi, sma=80000.0, hv14=0.40, hv7=0.35):
    tmp = tempfile.mkdtemp(); os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
    for fn, hist in (("prem_hist.csv", prem), ("iv_hist.csv", iv)):
        if hist is not None:
            with open(tmp + "/state/" + fn, "w", newline="") as fh:
                w = csv.writer(fh)
                for i, v in enumerate(hist):
                    w.writerow([(dt.date(2026, 11, 17) - dt.timedelta(days=2 * i)).isoformat(), v, "seed", ""])
    ind = dict(c1=82000.0, c2=81000.0, h1=82500.0, l1=80500.0, sma50=sma, hv14=hv14, hv7=hv7, hv365=0.38, atr14=2500.0, atr=2500.0, sl_acc=0.0, rsi4h=rsi)
    n = NL.Night(variant, 0.02, tmp); n.step(t0, 82000.0, chain(82000.0), ind)
    tr = [l for l in n.S["legs"] if l["set"] == "trend"]; assert len(tr) == 1, tr
    bo = sum(l["qty"] for l in n.S["legs"] if l["set"] == "boost"); ex = sum(l["qty"] for l in n.S["legs"] if l["set"] == "extra")
    return tr[0], round(bo, 4), round(ex, 4), n
def eq(a, b): assert abs(a - b) < 1e-9, (a, b)
print("--- 1 no flag: F stays 1x, H goes to half")
for v, want in (("v5aslf", 0.06), ("v5aslh", 0.03)):
    leg, bo, ex, n = run(v, HIGH, HIGH, 50.0); print(v, "trend leg", leg["qty"], leg["side"], "| other side", ex); eq(leg["qty"], want); eq(ex, 0.02); assert leg["side"] == "PE"
print("--- 2 each flag alone gives 1.5x (put sold)")
for nm, a in (("premium", (LOW, HIGH, 50.0)), ("volatility", (HIGH, LOW, 50.0)), ("4h RSI 65 with a put", (HIGH, HIGH, 65.0))):
    for v in ("v5aslf", "v5aslh"):
        leg, bo, ex, n = run(v, *a); print(nm, v, "trend leg", leg["qty"]); eq(leg["qty"], 0.09); eq(ex, 0.02)
        f = n.S["flags_night"]; assert [f["P"], f["V"], f["R"]].count(True) == 1 and f["mult"] == 1.5, f
print("--- 3 call sold: RSI under 40 is the flag, RSI 65 is not")
leg, bo, ex, n = run("v5aslf", HIGH, HIGH, 35.0, sma=90000.0); print("call, RSI 35:", leg["qty"], leg["side"]); eq(leg["qty"], 0.09); assert leg["side"] == "CE"
leg, bo, ex, n = run("v5aslh", HIGH, HIGH, 65.0, sma=90000.0); print("call, RSI 65:", leg["qty"]); eq(leg["qty"], 0.03)
print("--- 4 normal-volatility night with the boost: boost follows the trend leg")
for v, a, wt, wb in (("v5asl", (HIGH, HIGH, 50.0), 0.02, 0.01), ("v5aslf", (HIGH, HIGH, 65.0), 0.03, 0.015), ("v5aslh", (HIGH, HIGH, 50.0), 0.01, 0.005)):
    leg, bo, ex, n = run(v, *a, hv14=0.20, hv7=0.20); print(v, "trend", leg["qty"], "boost", bo); eq(leg["qty"], wt); eq(bo, wb)
print("--- 5 no RSI and short history: no flag can be on")
leg, bo, ex, n = run("v5aslf", LOW[:30], LOW[:30], None); eq(leg["qty"], 0.06)
leg, bo, ex, n = run("v5aslh", LOW[:30], LOW[:30], None); print("H with no data:", leg["qty"]); eq(leg["qty"], 0.03)
print("--- 6 the earlier copies are unchanged")
leg, bo, ex, n = run("v5asl", LOW, LOW, 65.0); eq(leg["qty"], 0.06); assert not n.flags and not n.rich
leg, bo, ex, n = run("v5aslp", LOW, LOW, 65.0); eq(leg["qty"], 0.09)
leg, bo, ex, n = run("v5aslp", HIGH, LOW, 65.0); eq(leg["qty"], 0.06)
leg, bo, ex, n = run("v5aslj", LOW, LOW, 65.0); eq(leg["qty"], 0.06); assert n.jump and not n.flags
print("--- 7 RSI arithmetic")
up = [100.0 + i for i in range(100)]; assert NB.rsi14(up) == 100.0 and NB.rsi14(up[:20]) is None
zig = [100.0 + (1 if i % 2 else 0) for i in range(200)]; r = NB.rsi14(zig); print("zig-zag RSI %.1f" % r); assert 45 < r < 55
print("SELFTEST FLAG PAPER PASSED")
