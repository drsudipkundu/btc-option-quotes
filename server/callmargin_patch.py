"""6-Nov-2026 (Sudip): server ladders' call leg checks MARGIN before every call sale (covered and extra).
Allowed call contracts = (available margin on the account - reserve for the ladder's buys on a 40 % fall) /
margin per option contract (mark x 0.001 x opt_im; opt_im 1.0 = 1x leverage as seen on Ladderv9).
Live only (paper copies have no account, unchanged). If the room is smaller, the sale is reduced; 0 -> no sale; emailed.
Idempotent, backup ladcall.py.bak_cmargin. No service restarted here (ladderlive picks it up at its next restart)."""
import os, sys, shutil
H = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/deltabot")
p = os.path.join(H, "ladcall.py"); s = open(p, encoding="utf-8").read()
if "def _mcap(" in s:
    print("ladcall.py already has the margin check"); sys.exit(0)
def rep(a, b):
    global s
    if s.count(a) != 1:
        raise SystemExit("ANCHOR PROBLEM (%d hits): %r - nothing written" % (s.count(a), a[:60]))
    s = s.replace(a, b)
rep('bb_from=1720, floor=1.0, retry_s=1800, max_tries=3, bb_cap=1.5, stop_cap=3.0, ue_cap=3.0)',
    'bb_from=1720, floor=1.0, retry_s=1800, max_tries=3, bb_cap=1.5, stop_cap=3.0, ue_cap=3.0,\n'
    '          mcheck=True, fall=0.40, gap_ref=0.0075, opt_im=1.0, fut_im=1.0)  # margin check (6-Nov-2026)')
rep('    def _job_done(self, now, spot, J, ladder, feed, sma, now_ts, hm):\n',
'''    def _mcap(self, want, ladder, mark, what):
        """Live only: cap a call sale so the ladder keeps money for its buys on a P['fall'] drop."""
        P = self.P
        if want < 1 or not P.get("mcheck") or self.mode == "paper" or not hasattr(self.ex, "cl"):
            return want
        try:
            bal = {b["asset"]: b for b in self.ex.cl.balance()}
            avail = float(bal.get("USD", {}).get("avail", 0))
            held = int(ladder.held())
            try:
                cap_c = int(ladder.brake + ladder.entry_c)
            except Exception:
                cap_c = 280
            n_lots = int(P["fall"] / P["gap_ref"])
            fall_c = max(0, min(n_lots * 4, cap_c - held))          # contracts the ladder may still buy
            reserve = fall_c * C * mark * (1 - P["fall"] / 2) * P["fut_im"]
            per = mark * C * P["opt_im"]
            room = int(max(0.0, avail - reserve) / per) if per > 0 else 0
        except Exception as e:
            self.log("%s call margin check failed (%s) - no %s sale" % (self.key, e, what))
            return 0
        if room < want:
            self.notify("%s call %s reduced %d -> %d (margin)" % (self.key, what, want, max(room, 0)),
                        "available %.0f USD, ladder reserve %.0f USD for a %d %% fall, %.1f USD margin per contract" % (
                            avail, reserve, int(P["fall"] * 100), per))
            self.log("%s call %s reduced %d -> %d (avail %.0f, reserve %.0f)" % (self.key, what, want, room, avail, reserve))
        return max(0, min(want, room))

    def _job_done(self, now, spot, J, ladder, feed, sma, now_ts, hm):
''')
rep('                    c = self.covered(ladder, o["strike"])\n',
    '                    c = self.covered(ladder, o["strike"])\n                    c = self._mcap(c, ladder, mark, "covered")\n')
rep('                xn = min(int(P["xmul"] * sold), int(round(P["xmax_btc"] / C)))\n',
    '                xn = min(int(P["xmul"] * sold), int(round(P["xmax_btc"] / C)))\n                xn = self._mcap(xn, ladder, spot, "extra")\n')
shutil.copy2(p, p + ".bak_cmargin")
open(p, "w", encoding="utf-8").write(s)
print("ladcall.py: margin check added (live only)")
