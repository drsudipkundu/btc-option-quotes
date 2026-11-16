"""offline check of letterbox.py in a throw-away folder: the fixed list, refusals, the Telegram wrapper. No network, no email, no order."""
import os, sys, json, tempfile, shutil, time
CODE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(); os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
for f in ("letterbox.py", "nightlive.py", "nightlogic.py", "autosize.py", "control.py", "guard.py"):
    shutil.copy(os.path.join(CODE, f), tmp)
os.environ["BOT_HOME"] = tmp; sys.path.insert(0, tmp)
import letterbox as LB
assert LB.HOME == tmp
try:
    json.dump(dict(armed=True, acct="test", base=0.06, rule="v5asl", wing=0.04), open(tmp + "/state/night_live_cfg.json", "w"))
    json.dump(dict(night="2026-11-16", legs=[], halt=None, total_pnl=1.0, nights=1), open(tmp + "/state/night_nlive.json", "w"))
    open(tmp + "/logs/x.log", "w").write("a\nb\nc\n")
    r = LB.run("wing", ["0"]); print(r); assert "OFF" in r and json.load(open(tmp + "/state/night_live_cfg.json"))["wing"] == 0
    r = LB.run("wing", ["4"]); print(r); assert "4.0 %" in r and json.load(open(tmp + "/state/night_live_cfg.json"))["wing"] == 0.04
    for bad in (["40"], ["-1"], ["4; rm -rf /"], ["4", "5"], []):
        assert LB.run("wing", bad).startswith("REFUSED"), bad
    r = LB.run("ceiling", ["0.2", "2026-11-18"]); print(r); assert json.load(open(tmp + "/state/autosize.json"))["ceiling"] == 0.2
    for bad in (["9"], ["0.5"], ["0.2", "tomorrow"], ["x"]):
        assert "REFUSED" in LB.run("ceiling", bad), bad
    assert LB.run("pause", []).startswith("PAUSED"); import control; assert control.get("nlive")["state"] == "paused"
    assert LB.run("resume", []).startswith("RESUMED") and control.get("nlive")["state"] == "running"
    for do, a in (("sell", []), ("exit", []), ("restart", ["sshd"]), ("restart", ["ladderlive"]), ("tail", ["../.env"]), ("tail", [".env"]), ("tail", ["x.log", "999"]), ("rm", ["x"]), ("autosize", ["--ceiling"])):
        r = LB.run(do, a); assert r.startswith("REFUSED"), (do, a, r)
    assert LB.run("tail", ["x.log", "2"]).endswith("b\nc")
    assert LB.run("clear_halt", []) == "There is no halt."
    s = LB.run("status", []); assert "SERVER STATUS" in s and "Hedge: ON" in s and ".env" not in s; print(s.splitlines()[0])
    st = {}
    assert LB.telegram("/hedge", st).startswith("Hedge: ON")
    assert "OFF" in LB.telegram("/hedge off", st) and "ON" in LB.telegram("/hedge on", st) and "6.0 %" in LB.telegram("/hedge 6", st)
    LB.telegram("/hedge on", st)
    assert LB.telegram("/exit", st).startswith("Nothing is open") and LB.telegram("/exit yes", st).startswith("Nothing is open")
    json.dump(dict(night="2026-11-16", legs=[dict(sym="P-BTC-60000-171126", dir="S", qty=0.18, entry=50, closed=False, kind="main")], halt="x"), open(tmp + "/state/night_nlive.json", "w"))
    assert LB.telegram("/exit yes", st).startswith("EXIT asks") and control.get("nlive")["state"] == "running"      # yes without asking first = asks
    st["exit_ask"] = time.time() - 500
    assert LB.telegram("/exit yes", st).startswith("EXIT asks") and control.get("nlive")["state"] == "running"      # too late = asks again
    assert LB.telegram("/exit yes", st).startswith("EXIT STARTED") and control.get("nlive")["state"] == "stopped"
    assert LB.run("clear_halt", []).startswith("REFUSED") and LB.run("restart", ["nightlive"]).startswith("REFUSED")
    print("SELFTEST LETTERBOX PASSED")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
