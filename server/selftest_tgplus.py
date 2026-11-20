"""offline self-test of tgplus (Telegram /pnl /cum /tonight /guard /paper /server /ceiling). No network: Delta answers are faked."""
import os, sys, json, tempfile, shutil, time, types, subprocess
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
tmp = tempfile.mkdtemp(); os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
os.environ["BOT_HOME"] = tmp
sys.path.insert(0, H)
import tgplus as TP
TP.HOME = tmp
def w(p, o): json.dump(o, open(os.path.join(tmp, p), "w"))
try:
    w("state/night_live_cfg.json", dict(base=0.12, base_big=0.18, flagmode="h", wing=0.04, rule="v5asl"))
    w("state/autosize.json", dict(ceiling=0.30, ceiling_from_ts=0))
    w("state/night_nlive.json", dict(night="2026-11-19", total_pnl=104.06, nights=15, cg={"PE": dict(ref=62700, atr=2600)},
      legs=[dict(id=1, set="trend", kind="main", side="CE", sym="C-BTC-65000-201126", strike=65000, qty=0.54, dir="S", entry=31.0, closed=True, pnl=13.2),
            dict(id=3, set="extra", kind="extra", side="PE", sym="P-BTC-60500-201126", strike=60500, qty=0.12, dir="S", entry=137.0, closed=False),
            dict(id=4, set="extra", kind="wing", side="PE", sym="P-BTC-57000-201126", strike=57000, qty=0.12, dir="B", entry=5.0, closed=False, cover=3)]))
    open(os.path.join(tmp, "logs/trades_night_nlive.csv"), "w").write(
        "2026-11-17 13:07,v5asl,2026-11-17,NIGHT-END,,,,,,0,0,17.269,x\n2026-11-18 09:19,v5asl,2026-11-18,NIGHT-END,,,,,,0,0,14.045,x\n2026-11-20 13:49,v5asl,2026-11-19,NIGHT-END,,,,,,0,0,-3.5,x\n")
    w("state/night_v5asl.json", dict(total_pnl=22.5, nights=10, legs=[])); w("state/night_v5aslh.json", dict(total_pnl=30.1, nights=3, legs=[]))
    TP._tk = lambda sym: (0.5, 0.6, 0.55, 61800.0) if "57000" in sym else (24.0, 25.0, 24.5, 61800.0)
    t = TP.pnl_text(); print(t); assert "P-BTC-60500" in t and "+13.20" in t and "booked" in t
    print("--- 1 /pnl: open legs priced, booked part counted")
    t = TP.cum_text(); print(t); assert "3 nights, 1 losing" in t and "+27.81" in t
    print("--- 2 /cum: total, losing nights, drop from peak")
    t = TP.guard_text(); print(t); assert "fully hedged" in t
    S = json.load(open(tmp + "/state/night_nlive.json")); S["legs"] = S["legs"][:2]; w("state/night_nlive.json", S)
    t = TP.guard_text(); print(t); assert "NOT fully hedged" in t and "60500" in t
    print("--- 3 /guard: hedged side and unhedged side")
    def fake_get(path, q=None):
        now = int(time.time())
        if path == "/v2/history/candles":
            n = 80 if q["resolution"] == "1d" else 240
            return [dict(time=now - (n - i) * 3600, close=60000 + 50 * i) for i in range(n)]
        if path == "/v2/tickers":
            return [dict(contract_type="put_options", strike_price="59000", spot_price="61800"), dict(contract_type="call_options", strike_price="66000", spot_price="61800")]
    TP._get = fake_get
    t = TP.tonight_text(); print(t); assert "small 0.12" in t and "big 0.18" in t and "4h RSI" in t and "puts down to 59000" in t
    print("--- 4 /tonight: bases, side, RSI flag, strikes listed")
    t = TP.paper_text(); print(t); assert "+30.10" in t
    print("--- 5 /paper: copies sorted by profit")
    t = TP.server_text(); print(t.splitlines()[0]); assert "SERVER" in t
    print("--- 6 /server")
    st = {}
    assert "0.30" in TP.ceiling_cmd([], st)
    assert "REFUSED" in TP.ceiling_cmd(["0.5"], st)
    assert "asks" in TP.ceiling_cmd(["0.25"], st)
    ran = []
    real = subprocess.run
    TP.subprocess = types.SimpleNamespace(run=lambda args, **k: ran.append(args) or types.SimpleNamespace(stdout="ceiling: 0.25 BTC", stderr=""))
    t = TP.ceiling_cmd(["yes"], st); print(t); assert ran and ran[0][-1] == "0.25" and "CHANGED" in t
    assert "Nothing waiting" in TP.ceiling_cmd(["yes"], st)
    st2 = {}; TP.ceiling_cmd(["0.2"], st2); st2["ceil_ask"] -= 200; assert "Nothing waiting" in TP.ceiling_cmd(["yes"], st2)
    print("--- 7 /ceiling: shows, refuses above 0.30, asks, applies only on yes within 3 minutes")
    print("SELFTEST TELEGRAM PLUS PASSED")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
