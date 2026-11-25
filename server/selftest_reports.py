"""offline self-test of reports.py (25-Nov-2026 c16): the scheduled Telegram + Gmail reports. Throw-away folder, pretend prices, pretend Telegram/Gmail; no network, no order.
 1 plan (22:00): sales ON; settings line; tonight preview; SIZE CALCULATION with balance, money per 0.01, small and big base, ceiling and the rules (moved night, opposite leg, slope)
 2 plan with sales OFF (state paused) -> says SALES ARE OFF and what to send; with a halt -> shows the halt
 3 decision (23:33) after a sale: legs, hedge cover, trend leg = base x 3/1 x flags with the numbers, opposite leg, top-up line; before a sale: NO SALE + reason
 4 position (23:50): per side sold/hedge, expected profit three ways (all expire, at the take-profit, worst case), earned share, daily result
 5 status (07:00/17:22): open profit lines, earned share, no-position case
 6 a broken part (price feed fails) does not stop the report: one short line instead
 7 watch: change -> quiet 2 minutes -> ONE status; no second status without a change; first ever run says nothing
 8 send: Telegram text split under 3,900 characters; Gmail copy sent"""
import os, sys, json, tempfile, shutil, time, types
CODE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(); os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
for f in os.listdir(CODE):
    if f.endswith(".py") and not f.startswith("selftest"):
        shutil.copy(os.path.join(CODE, f), tmp)
os.environ["BOT_HOME"] = tmp
sys.path.insert(0, tmp)
SENT, MAILS = [], []
nw = types.ModuleType("nightwatch"); nw.tg_send = lambda t: SENT.append(t) or True
sys.modules["nightwatch"] = nw
class _N:
    def _send_now(self, s, b): MAILS.append((s, b))
bot = types.ModuleType("bot"); bot.Notifier = _N; sys.modules["bot"] = bot
dotenv = types.ModuleType("dotenv"); dotenv.load_dotenv = lambda *a, **k: None; sys.modules["dotenv"] = dotenv
import control, autosize as A, sizecalc as SC, tgplus as T, reports as R
assert R.HOME == tmp
IND = dict(hv14=0.31, hv7=0.30, hv365=0.45, atr=2200.0, atr14=2200.0, sl_acc=0.0, c1=60500.0, c2=60000.0, sma50=62000.0, h1=61000.0, l1=59800.0)
A.read_all = lambda: (7200.0, 60000.0, [], 4300.0, 85.0, lambda t: None, 2900.0)
SC.tonight_ind = lambda: dict(IND)
def fake_tk(sym):
    return (30.0, 33.0, 31.0, 60000.0)
T._tk = fake_tk
def fake_get(path, q=None):
    if "candles" in path:
        return [dict(time=i, close=60000 + i * 10) for i in range(90)]
    return [dict(strike_price=str(k), contract_type="put_options" if k < 60000 else "call_options", spot_price="60000") for k in range(54000, 66000, 200)]
T._get = fake_get
CF, SF = tmp + "/state/night_live_cfg.json", tmp + "/state/night_nlive.json"
def put(S=None, **c):
    cfg = dict(armed=True, acct="serverbot", base=0.16, base_big=0.27, rule="v5asl", wing=0.04, juice=0.05, juice_once=0, flagmode="h", retry_lim=1)
    cfg.update(c)
    json.dump(cfg, open(CF, "w"))
    json.dump(S if S is not None else dict(night="2026-11-24", legs=[], halt=None, total_pnl=324.47, nights=20, last_night=dict(night="2026-11-24", pnl=8.8, legs=6)), open(SF, "w"))
today = time.strftime("%Y-%m-%d")
def legs():
    L = [dict(id=1, set="trend", kind="main", side="CE", sym="C-BTC-61800-261126", strike=61800.0, qty=0.72, dir="S", entry=32.5, closed=False, fee=0.5),
         dict(id=2, set="wing", kind="wing", side="CE", sym="C-BTC-64200-261126", strike=64200.0, qty=0.72, dir="B", entry=12.0, closed=False, fee=0.2, cover=1),
         dict(id=3, set="extra", kind="extra", side="PE", sym="P-BTC-57400-261126", strike=57400.0, qty=0.16, dir="S", entry=77.0, closed=False, fee=0.2),
         dict(id=4, set="wing", kind="wing", side="PE", sym="P-BTC-55200-261126", strike=55200.0, qty=0.16, dir="B", entry=12.0, closed=False, fee=0.1, cover=3)]
    return L
try:
    # 1
    put(); os.makedirs(tmp, exist_ok=True)
    p = R.plan_report(); print(p)
    for k in ("PLAN", "Sales are ON", "Settings:", "take-profit closes at 95", "TONIGHT", "SIZE CALCULATION", "Small base = balance / 4300", "Big base = balance / 2900",
              "Live now: small 0.16, big 0.27", "MOVED", "Opposite leg", "Running total"):
        assert k in p, k
    # 2
    cj = json.load(open(CF)); cj["armed"] = False; json.dump(cj, open(CF, "w"))
    assert "SALES ARE OFF" in R.plan_report() and "not armed" in R.plan_report()
    put(S=dict(night="2026-11-24", legs=[], halt="position mismatch", total_pnl=1, nights=1)); assert "HALT: position mismatch" in R.plan_report()
    # 3
    put(S=dict(night=today, legs=legs(), halt=None, plan=dict(trend=0.72, extra=0.16), flags_night=dict(night=today, P=True, V=False, R=False, mult=1.5), topup_sides=dict(night=today, sides=["PE"]), total_pnl=324.47, nights=20))
    d = R.decision_report(); print(d)
    for k in ("DECISION", "CALL: SOLD 720 contracts", "covers 100 %", "small base 0.16", "flags 1.50", "Opposite leg 0.160", "Top-up:", "done for: PE"):
        assert k in d, k
    put(); d = R.decision_report(); assert "NO SALE" in d and "Sales are ON" in d
    # 4
    put(S=dict(night=today, legs=legs(), halt=None, plan=dict(trend=0.72, extra=0.16), flags_night=dict(night=today, mult=1.5), topup_sides=dict(night=today, sides=["PE", "CE"]), total_pnl=324.47, nights=20, last_night=dict(night="2026-11-24", pnl=8.8)))
    s = R.position_report(); print(s)
    for k in ("EXPECTED PROFIT", "1) If everything expires worthless", "2) At your take-profit (95 %", "3) Theoretical maximum loss on the call side", "Earned so far", "Last finished night 2026-11-24"):
        assert k in s, k
    ex = 0.72 * 32.5 + 0.16 * 77.0 - 0.72 * 12.0 - 0.16 * 12.0 - (0.5 + 0.2 + 0.2 + 0.1)
    assert ("%+.2f USD" % ex) in s, ("expected", ex)
    # 5
    st = R.status_report(); print(st)
    assert "PNL night" in st and "Earned so far" in st and "17:30 IST" in st
    put(); assert "No position is open." in R.status_report()
    # 6
    put(S=dict(night=today, legs=legs(), halt=None, plan=dict(trend=0.72), total_pnl=1, nights=1))
    def boom(sym): raise RuntimeError("feed down")
    T._tk = boom
    r = R.position_report(); assert "POSITION" in r and "not available" in r and "SOLD 720" in r
    T._tk = fake_tk
    # 7
    for f in ("reports_seen.json",):
        try: os.remove(tmp + "/state/" + f)
        except OSError: pass
    put(S=dict(night=today, legs=[], halt=None, total_pnl=1, nights=1))
    SENT.clear(); MAILS.clear()
    assert R.watch() == "changed" and not SENT                       # first ever run: nothing sent
    time.sleep(0.1); assert R.watch() == "quiet" and not SENT
    put(S=dict(night=today, legs=legs(), halt=None, plan=dict(trend=0.72), total_pnl=1, nights=1))
    assert R.watch() == "changed" and not SENT
    w = json.load(open(tmp + "/state/reports_seen.json")); w["changed"] -= 130; json.dump(w, open(tmp + "/state/reports_seen.json", "w"))
    import datetime as _d
    r = R.watch(); hm = _d.datetime.now(R.IST).hour * 100 + _d.datetime.now(R.IST).minute
    if hm >= 2330 or hm < 1800:
        assert r == "sent" and SENT and MAILS, r
        assert R.watch() == "quiet" and len(MAILS) == 1
    else:
        assert r == "quiet"; print("   (watch send skipped at this clock time: outside 23:30-18:00)")
    # 8
    SENT.clear(); MAILS.clear()
    ok = R.send("test", "x" * 9000)
    assert ok == ["telegram", "gmail"] and len(SENT) == 3 and all(len(t) <= 3800 for t in SENT) and MAILS and MAILS[0][0].startswith("[DeltaBot LIVE] REPORT")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nSELFTEST REPORTS PASSED")
