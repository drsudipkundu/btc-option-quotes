"""offline self-test of richpaper_patch: paper copy v5aslp sells the trend leg 1.5 x only when tonight's premium is in the top 10 % of
its last 365 days; v5asl is unchanged. No network, no orders."""
import os, sys, csv, datetime as dt, tempfile
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot")); sys.path.insert(0, H)
import nightlogic as NL
IST = NL.IST; exp = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc).timestamp()
def chain(spot):
    out = []
    for k in range(60000, 100001, 200):
        for typ in ("PE", "CE"):
            d = abs(k - spot) / spot
            px = max(0.5, 3000 * max(0.0, 0.06 - d)) if ((typ == "PE" and k < spot) or (typ == "CE" and k > spot)) else 3000.0
            out.append(dict(sym="%s-BTC-%d-191126" % ("P" if typ == "PE" else "C", k), typ=typ, strike=float(k), exp=exp, bid=px, ask=px * 1.05 + 0.5, mark=px * 1.02, iv=0.3, oi=0.0, ro=False))
    return out
ind = dict(c1=82000.0, c2=81000.0, h1=82500.0, l1=80500.0, sma50=80000.0, hv14=0.40, hv7=0.35, hv365=0.38, atr14=2500.0, atr=2500.0, sl_acc=0.0)
t0 = dt.datetime(2026, 11, 18, 23, 31, tzinfo=IST)
def run(variant, hist):
    tmp = tempfile.mkdtemp(); os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
    if hist is not None:
        with open(tmp + "/state/prem_hist.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            for i, v in enumerate(hist):
                w.writerow([(dt.date(2026, 11, 17) - dt.timedelta(days=2 * i)).isoformat(), v, "seed", ""])
    n = NL.Night(variant, 0.02, tmp); n.step(t0, 82000.0, chain(82000.0), ind)
    tr = [l for l in n.S["legs"] if l["set"] == "trend"]; assert len(tr) == 1, tr
    p = tmp + "/state/prem_hist.csv"; lines = open(p).read().splitlines() if os.path.exists(p) else []
    return tr[0], lines, n
low = [0.02 + 0.0005 * i for i in range(120)]            # tonight (about 0.09 %) is above all of them
high = [0.10 + 0.001 * i for i in range(120)]            # tonight is below all of them
print("--- 1 premium in the top 10 % of the last year")
leg, lines, n = run("v5aslp", low); print("trend leg", leg["qty"], "| premium %.3f %% of BTC" % (leg["entry"] / 82000 * 100)); assert abs(leg["qty"] - 0.09) < 1e-9 and n.rich and n.sl and not n.jump
assert lines[-1].startswith("2026-11-18"), lines[-1]
print("--- 2 ordinary premium")
leg, lines, n = run("v5aslp", high); print("trend leg", leg["qty"]); assert abs(leg["qty"] - 0.06) < 1e-9 and lines[-1].startswith("2026-11-18")
print("--- 3 history shorter than 60 nights")
leg, lines, n = run("v5aslp", low[:40]); print("trend leg", leg["qty"]); assert abs(leg["qty"] - 0.06) < 1e-9
print("--- 4 history older than 365 days is ignored")
tmpn = [0.02] * 5
leg, lines, n = run("v5aslp", [0.5] * 100 + [0.02] * 400); print("trend leg", leg["qty"]); assert abs(leg["qty"] - 0.06) < 1e-9
print("--- 5 the ordinary copy V5A-CG-SL is unchanged and keeps no history")
leg, lines, n = run("v5asl", None); print("trend leg", leg["qty"]); assert abs(leg["qty"] - 0.06) < 1e-9 and not lines and not n.rich
leg, lines, n = run("v5asl", low); assert abs(leg["qty"] - 0.06) < 1e-9 and len(lines) == 120
print("SELFTEST RICH PAPER PASSED")
