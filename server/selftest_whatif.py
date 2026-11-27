#!/usr/bin/env python3
"""selftest_whatif - pure-function test of whatif.py (paper only). No network, no order."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); TMP = tempfile.mkdtemp(); os.makedirs(TMP + "/logs"); os.environ["BOT_HOME"] = TMP; sys.path.insert(0, HERE)
n = [0]
def ok(c, m):
    if not c: print("FAIL:", m); sys.exit(1)
    n[0] += 1
import whatif as W
src = open(os.path.join(HERE, "whatif.py")).read()
ok("place_order" not in src and "requests.post" not in src and "requests.delete" not in src, "no order code")
ok(W.intrinsic("CE", 63000, 64000) == 1000 and W.intrinsic("CE", 63000, 62000) == 0 and W.intrinsic("PE", 58000, 57000) == 1000 and W.intrinsic("PE", 58000, 59000) == 0, "intrinsic")
# 16-Nov night: sold CE 67600 bought back at 2.0, S 64969 -> OTM, gain 0.18*2 + fee
ok(abs(W.hold_gain("sold", 2.0, 0.18, 0.0, 0.0149) - 0.3749) < 1e-6, "sold OTM gain")
ok(abs(W.hold_gain("hedge", 0.3, 0.18, 0.0, 0.0022) - (-0.054 + 0.0022)) < 1e-6, "hedge OTM loses resale value")
ok(W.hold_gain("sold", 25, 0.1, 200.0, 0.0) < 0, "sold ITM: holding would have cost more")
ok(W.hold_gain("hedge", 13, 0.16, 300.0, 0.0) > 0, "hedge ITM: holding would have paid")
import datetime as dt
ok(W.expiry_of("C-BTC-63000-271126") == dt.datetime(2026, 11, 27, 17, 30, tzinfo=W.IST), "expiry date")
# settlement from fake candles; not expired -> None
import time
exp = dt.datetime.fromtimestamp(time.time() - 3600, W.IST)
end = int(exp.timestamp())
fake = {"result": [{"time": end - 60 * i, "close": 100.0 + i} for i in range(1, 41)]}
S = W.settlement(exp, get=lambda u: fake)
ok(S is not None and 100 < S < 140, "settlement average")
ok(W.settlement(dt.datetime.fromtimestamp(time.time() + 3600, W.IST), get=lambda u: fake) is None, "not expired -> None")
rows = [dict(night="a", event="NIGHT-END", note="stopped by you", time_ist="t", symbol="s"), dict(night="a", event="EXIT-STOP", note="", time_ist="t", symbol="s"),
        dict(night="b", event="NIGHT-END", note="closed early (90%)", time_ist="t", symbol="s"), dict(night="b", event="EXIT-STOP", note="", time_ist="t", symbol="s")]
ok(len(W.legs_closed_by_hand(rows)) == 1, "only hand-stopped nights")
print("SELFTEST WHATIF PASSED (%d checks)" % n[0])
