"""offline check of the /stop and /go patch: applies it to a copy of letterbox.py in a throw-away folder, runs the commands, checks the flags and the guards in sweep_report / stagedrel / entry_shadow. No network, no order."""
import os, sys, json, tempfile, shutil, importlib
CODE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(); os.makedirs(tmp + "/state"); os.makedirs(tmp + "/logs")
for f in ("letterbox.py", "nightlive.py", "nightlogic.py", "autosize.py", "control.py", "guard.py"):
    if os.path.exists(os.path.join(CODE, f)):
        shutil.copy(os.path.join(CODE, f), tmp)
os.environ["BOT_HOME"] = tmp; sys.path.insert(0, tmp)
ok = []
try:
    import botstop_patch as P
    P.main()
    ok.append("patch applied once")
    assert open(tmp + "/letterbox.py").read().count("def botswitch(") == 1
    import letterbox as LB
    assert "/stop" in LB.TG_CMDS and "/go" in LB.TG_CMDS and "/install" in LB.TG_CMDS
    assert any(c[0] == "stop" for c in LB.CODES)
    r = LB.telegram("/stop", {}); assert "sweep: running" in r and "paperboy: running" in r, r
    r = LB.telegram("/stop sweep", {}); assert r.startswith("STOPPED: sweep"), r
    off = json.load(open(tmp + "/state/bots_off.json")); assert "sweep" in off and "emergency" not in off
    r = LB.telegram("/stop", {}); assert "sweep: STOPPED" in r and "emergency: running" in r, r
    r = LB.telegram("/stop all", {}); assert set(json.load(open(tmp + "/state/bots_off.json"))) == {"sweep", "emergency", "paperboy"}
    r = LB.telegram("/go emergency", {}); assert r.startswith("STARTED: emergency") and "emergency" not in json.load(open(tmp + "/state/bots_off.json"))
    r = LB.telegram("/stop banana", {}); assert r.startswith("REFUSED"), r
    r = LB.telegram("/go all", {}); assert json.load(open(tmp + "/state/bots_off.json")) == {}
    assert LB.telegram("/install", {}) and LB.codes_text()
    ok.append("/stop /go commands")
    # the bots honour the flag
    json.dump({"sweep": 1, "emergency": 1, "paperboy": 1}, open(tmp + "/state/bots_off.json", "w"))
    sys.path.insert(0, CODE)
    import sweep_report as SR, stagedrel as SD, entry_shadow as ES
    SR.STATE = tmp + "/state"; SD.STATE = tmp + "/state"; ES.HOME = tmp
    assert SR.bot_off("sweep") and SD.bot_off("emergency") and ES.bot_off("paperboy") and not SR.bot_off("x")
    sys.argv = ["sweep_report.py"]; assert SR.main() is None            # stopped: returns before any network call
    sys.argv = ["stagedrel.py"]; assert SD.main() is None
    assert "STOPPED" in json.load(open(tmp + "/state/stagedrel_status.json"))["text"]
    os.remove(tmp + "/state/bots_off.json")
    assert not SR.bot_off("sweep") and not ES.bot_off("paperboy")
    ok.append("bots honour the flag")
    print("BOTSTOP SELFTEST PASSED: " + ", ".join(ok))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
