"""offline self-test of the sales-stopped reminder (no orders, no exchange)"""
import os, sys, datetime as dt
CODE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(os.environ.get("REMIND_SRC", CODE), "nightlive.py"), encoding="utf-8").read()
a = src.index("def stopped_reminder(")
b = src.index("def main():", a)
ns = {}
exec(src[a:b], ns)
f = ns["stopped_reminder"]
D = lambda h, m: dt.datetime(2026, 11, 25, h, m)
ok = True
def chk(name, cond):
    global ok
    print(("OK   " if cond else "FAIL ") + name); ok = ok and cond
r = set()
chk("running and armed: no reminder", f(D(22, 30), "running", False, True, r) is None)
m = f(D(22, 31), "stopped", False, True, r)
chk("stopped at 22:31: reminder with /resume", m is not None and "/resume" in m and "stopped" in m)
chk("same slot not repeated", f(D(22, 45), "stopped", False, True, r) is None)
chk("second slot 23:10 sends once", f(D(23, 10), "stopped", False, True, r) is not None and f(D(23, 20), "stopped", False, True, r) is None)
chk("before 22:30: none", f(D(22, 29), "stopped", False, True, set()) is None)
chk("after 23:28: none", f(D(23, 29), "stopped", False, True, set()) is None)
chk("STOP file counts", "STOP file" in (f(D(22, 40), "running", True, True, set()) or ""))
chk("not armed counts", "not armed" in (f(D(22, 40), "running", False, False, set()) or ""))
chk("next day new slot", f(dt.datetime(2026, 11, 26, 22, 31), "stopped", False, True, r) is not None)
print("PASSED" if ok else "FAILED"); sys.exit(0 if ok else 1)
