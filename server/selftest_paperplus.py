"""offline self-test of paperplus_patch: paper copies v5aslk (guard at strike), v5asl15 (guard 1.5 ATR), v5aslhk (flags H + hedge-exists + guard at strike).
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
def run(variant, prem, iv, rsi, sma=80000.0, hv14=0.40, hv7=0.35, cut=None):
    tmp = tempfile.mkdtemp(); os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
    for fn, hist in (("prem_hist.csv", prem), ("iv_hist.csv", iv)):
        if hist is not None:
            with open(tmp + "/state/" + fn, "w", newline="") as fh:
                w = csv.writer(fh)
                for i, v in enumerate(hist):
                    w.writerow([(dt.date(2026, 11, 17) - dt.timedelta(days=2 * i)).isoformat(), v, "seed", ""])
    ind = dict(c1=82000.0, c2=81000.0, h1=82500.0, l1=80500.0, sma50=sma, hv14=hv14, hv7=hv7, hv365=0.38, atr14=2500.0, atr=2500.0, sl_acc=0.0, rsi4h=rsi)
    ch = [o for o in chain(82000.0) if not (cut and o['typ'] == 'PE' and o['strike'] < cut)]
    n = NL.Night(variant, 0.02, tmp); n.step(t0, 82000.0, ch, ind); n._ind = ind; n._ch = ch
    tr = [l for l in n.S["legs"] if l["set"] == "trend"]; assert len(tr) == 1, tr
    bo = sum(l["qty"] for l in n.S["legs"] if l["set"] == "boost"); ex = sum(l["qty"] for l in n.S["legs"] if l["set"] == "extra")
    return tr[0], round(bo, 4), round(ex, 4), n
def eq(a, b): assert abs(a - b) < 1e-9, (a, b)

def ins(n): return [l for l in n.S["legs"] if l.get("kind") == "ins"]
print("--- 1 HK: flag on and a far put on offer -> trend leg x1.5")
leg, bo, ex, n = run("v5aslhk", LOW, HIGH, 50.0); K = leg["strike"]; print("HK trend", leg["qty"], "put sold at", K); eq(leg["qty"], 0.09)
print("--- 2 HK: flag on but nothing listed below the sold put -> stays 1x")
leg, bo, ex, n = run("v5aslhk", LOW, HIGH, 50.0, cut=K); eq(leg["qty"], 0.06)
print("--- 3 HK: no flag -> half")
leg, bo, ex, n = run("v5aslhk", HIGH, HIGH, 50.0); eq(leg["qty"], 0.03)
print("--- 4 guard levels after the sale (BTC falls overnight)")
t1 = dt.datetime(2026, 11, 19, 0, 31, tzinfo=IST)
res = {}
for v in ("v5asl", "v5asl15", "v5aslk"):
    for sp in (K - 10.0, 78200.0):
        leg, bo, ex, n = run(v, HIGH, HIGH, 50.0)
        n.step(t1, sp, chain(sp), n._ind)
        res[(v, sp)] = bool(ins(n))
print(res)
assert res[("v5aslk", K - 10.0)] and not res[("v5asl", K - 10.0)] and not res[("v5asl15", K - 10.0)]
assert res[("v5asl15", 78200.0)] and not res[("v5asl", 78200.0)]
rows = open(n.csv_path).read(); assert "(strike)" in rows or "(atr)" in rows, rows[-300:]
print("    K fires at the sold strike, G15 at 1.5 x ATR, plain V5A-CG-SL only at 2 x ATR; insurance row names the mode")
print("--- 5 earlier copies unchanged")
for v in ("v5asl", "v5aslf", "v5aslh", "v5aslp", "v5aslj"):
    n = NL.Night(v, 0.02, tempfile.mkdtemp())
    assert not hasattr(n, "hedge_ok") and not n.gk_unhedged and n.cg_mult == NL.CG_MULT, v
assert NL.Night("v5aslh", 0.02, tempfile.mkdtemp()).noflag_mult == 0.5 and NL.Night("v5aslf", 0.02, tempfile.mkdtemp()).flags
print("SELFTEST PAPER PLUS PASSED")
