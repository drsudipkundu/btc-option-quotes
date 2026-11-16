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
    t = LB.telegram("/codes", st); assert t == LB.telegram("/help", st) and all(("/" + c) in t for c, d in LB.CODES) and "ack" in t
    assert all(c == c.lower() and 1 <= len(c) <= 32 and c.isalnum() and 3 <= len(d) <= 256 for c, d in LB.CODES)
    # ---- read-only Delta looks: argument checks only (no network here)
    for do, bad in (("quote", ["BTC"]), ("quote", ["C-BTC-1-1; ls"]), ("quote", []), ("chain", ["X"]), ("chain", []), ("fills", ["999"]), ("fills", ["a"])):
        assert LB.run(do, bad).startswith("REFUSED"), (do, bad)
    assert LB.run("orders", []).startswith("FAILED") or "order" in LB.run("orders", []).lower()      # no key here: fails cleanly, no crash
    assert set(c[1:] for c in LB.TG_CMDS if c[1:] in LB.ACTIONS) >= {"orders", "fills", "quote", "chain"}
    assert LB._t("2026-11-16T10:00:00Z") == "16-Nov 15:30:00" and LB._t(1794823200000000) == LB._t(1794823200)
    # ---- update with Sudip's yes
    sha = "a" * 40
    assert LB.install_text() == "No update is waiting."
    for bad in (["x.sh"], ["install_x.sh; rm"], ["../install_x.sh"], [], ["install_a.sh", "b"]):
        assert LB.request_install("t1", bad, "n", sha).startswith("REFUSED"), bad
    assert LB.request_install("t1", ["install_x.sh"], "n", "zz").startswith("REFUSED")
    sent, LB.answer = [], (lambda subj, body: sent.append((subj, body)))
    LB.curl = lambda url, extra=(): "echo RUNNING $1; echo %s" % url.split("/")[-1]
    assert "WAITING" in LB.request_install("t1", ["install_x.sh"], "test update", sha)
    LB.run_approved(); assert not sent                                      # not approved = nothing runs
    assert LB.telegram("/install", st).startswith("Waiting for your yes")
    assert LB.telegram("/install no", st).startswith("Update dropped"); LB.run_approved(); assert not sent
    assert LB.telegram("/install yes", st) == "No update is waiting."
    LB.request_install("t2", ["install_x.sh"], "test update", sha)
    pj = json.load(open(LB.PEND_F)); pj["asked"] -= 3600; json.dump(pj, open(LB.PEND_F, "w"))
    assert "lapsed" in LB.telegram("/install yes", st); LB.run_approved(); assert not sent      # too late = nothing runs
    LB.request_install("t3", ["install_x.sh"], "test update", sha)
    assert LB.telegram("/install yes", st).startswith("APPROVED")
    LB.run_approved(); assert len(sent) == 1 and "DONE" in sent[0][0] and "RUNNING " + sha in sent[0][1] and "install_x.sh" in sent[0][1], sent
    LB.run_approved(); assert len(sent) == 1                                # never twice
    assert LB.telegram("/install yes", st) == "No update is waiting."
    print("SELFTEST LETTERBOX PASSED")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
