"""offline self-test of v5live_patch: (1) paper v5aslj sells trend + opposite leg, then jumps the opposite leg; (2) the live seller class
takes its rules from the config and plans v5 sizes with the strike jump off. No network, no orders."""
import os, sys, json, datetime as dt, tempfile, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot")); sys.path.insert(0, H)
import nightlogic as NL
tmp = tempfile.mkdtemp(); os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
IST = NL.IST; exp = dt.datetime(2026, 11, 17, 12, 0, tzinfo=dt.timezone.utc).timestamp()
def chain(spot):
    out = []
    for k in range(60000, 100001, 200):
        for typ in ("PE", "CE"):
            d = abs(k - spot) / spot
            px = max(0.5, 3000 * max(0.0, 0.06 - d)) if ((typ == "PE" and k < spot) or (typ == "CE" and k > spot)) else 3000.0
            out.append(dict(sym="%s-BTC-%d-171126" % ("P" if typ == "PE" else "C", k), typ=typ, strike=float(k), exp=exp, bid=px, ask=px * 1.05 + 0.5, mark=px * 1.02, iv=0.9, oi=0.0, ro=False))
    return out
ind = dict(c1=82000.0, c2=81000.0, h1=82500.0, l1=80500.0, sma50=80000.0, hv14=0.40, hv7=0.35, hv365=0.38, atr14=2500.0, atr=2500.0, sl_acc=0.0)
n = NL.Night("v5aslj", 0.02, tmp); assert n.jump and n.sl and n.rule == "v5a"
t0 = dt.datetime(2026, 11, 16, 23, 31, tzinfo=IST)
n.step(t0, 82000.0, chain(82000.0), ind)
legs = [(l["set"], l["side"], l["strike"], l["qty"]) for l in n.open_legs()]; print("after sale:", legs)
assert any(l[0] == "trend" and l[1] == "PE" for l in legs) and any(l[0] == "extra" and l[1] == "CE" for l in legs)
n.step(t0 + dt.timedelta(seconds=20), 82000.0, chain(82000.0), ind)          # reference price tick
tr = [l for l in n.open_legs() if l["set"] == "trend"][0]; half = (82000.0 + tr["strike"]) / 2
n.step(t0 + dt.timedelta(hours=2), half + 300, chain(half + 300), ind); assert "jump" not in n.S["fired"], "jumped too early"
n.step(t0 + dt.timedelta(hours=3), half - 50, chain(half - 50), ind)
legs2 = [(l["set"], l["side"], l["strike"], l["qty"], l["closed"]) for l in n.S["legs"]]; print("after jump:", legs2)
assert "jump" in n.S["fired"] and any(l[0] == "extra2" and not l[4] for l in legs2) and all(l[4] for l in legs2 if l[0] == "extra")
new = [l for l in legs2 if l[0] == "extra2"][0]; old = [l for l in legs2 if l[0] == "extra"][0]; assert new[2] < old[2] and new[3] == old[3]
n2 = NL.Night("v5asl", 0.02, tmp); assert not n2.jump and n2.sl
n3 = NL.Night("v4asl", 0.02, tmp); assert not n3.jump and n3.sl and n3.rule == "v4a"
print("PAPER STRIKE JUMP: OK   (opposite leg moved from %.0f to %.0f)" % (old[2], new[2]))
# ---- live class: rules from the config, no orders placed here
try:
    import nightlive as LV
    for rule, want in (("v4asl", [0.04]), ("v5asl", [0.06, 0.02])):
        json.dump(dict(rule=rule, base=0.02, armed=False), open(LV.CFG_F + ".selftest", "w"))
        real = LV.cfg
        LV.cfg = lambda: dict(LV.DEF, **json.load(open(LV.CFG_F + ".selftest")))
        x = LV.LiveNight(None, 0.02, lambda *a: None, lambda *a: None); LV.cfg = real
        got = [round(p["qty"], 3) for p in x.plan(ind)]
        print("live class with rule %s: label %s, tonight's plan sizes %s, strike jump %s" % (rule, x.lab, got, x.jump)); assert got == want and x.jump is False
    os.remove(LV.CFG_F + ".selftest")
    print("LIVE RULE SWITCH: OK   (current live config: rule %s)" % LV.cfg().get("rule"))
except ImportError as e:
    print("live class not importable here (%s) - skipped" % e)
shutil.rmtree(tmp)
print("SELFTEST PASSED")
