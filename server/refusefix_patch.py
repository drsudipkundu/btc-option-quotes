#!/usr/bin/env python3
"""refusefix_patch (24-Nov-2026, Sudip 24-Nov 00:11-00:27, "all accepted").
Problem (23-Nov night): Delta refused the far CALL hedge (HTTP 400 only_reduce_only_orders_allowed = the strike was at its open-interest cap).
An order the exchange REFUSES raised an error that ended the whole job, so the other strikes were never tried (hedge buyer AND smart sell AND
insurance buy). The call hedge was bought only 1 h 39 min later by the 5-minute retry.
Fix: in the one place where a NEW (not reduce-only) order is sent, an exchange refusal (text contains "HTTP 400") now counts as a FAILED TRY:
the order returns 0 filled instead of raising. The jobs then do what they were always meant to do, with YOUR existing settings:
  hedge buy: 3 tries per strike, 5 s apart, then up to 4 strikes further out, then the strikes in between;
  smart sell: polite offer, 3 retries 3 min apart on the first strike, then up to 4 strikes further out, one sweep each;
  insurance buy: the same strike list and tries as before.
Not changed: size limits (guard), the crash guard, reduce-only orders (buy-backs, exits - their errors still raise), network/key errors
(still raise), prices, caps, retry counts and gaps.
One message (Telegram + e-mail) per attempt lists every strike Delta refused and why (each strike/reason only once per night).
The hedge candidate list also leaves out strikes the chain already shows as capped (o["ro"], via is_full) - only if the line is found.
Every edit must match exactly once, otherwise NOTHING is written. Backup: nightlive.py.bak1124r"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

PLACE_OLD = "        o = self.cl.place(sym, side, int(n), price, reduce_only, cid)\n"
PLACE_NEW = '''        try:
            o = self.cl.place(sym, side, int(n), price, reduce_only, cid)
        except Exception as _e:                      # refusefix 24-Nov: a refused NEW order is a failed try, not a stop
            if reduce_only or "HTTP 400" not in str(_e):
                raise
            self._refused_note(sym, side, n, price, str(_e))
            return 0, 0.0, 0.0
'''

CAND_OLD = '''        same = [o for o in (self.ch or []) if o["typ"] == leg["side"] and (not exp or o["exp"] == exp)]\n'''
CAND_NEW = '''        same = [o for o in (self.ch or []) if o["typ"] == leg["side"] and (not exp or o["exp"] == exp) and not is_full(o, self.S.get("full", []))]\n'''

TAIL_ANCHOR = 'if __name__ == "__main__":\n'
TAIL = '''# ---- refusefix (24-Nov-2026): a strike the exchange refuses counts as a failed try; one message lists them -------------
def _refused_note(self, sym, side, n, price, why):
    if not hasattr(self, "_refused"):
        self._refused = []
    self._refused.append((sym, side, int(n), price, why[:200]))
    self.log("strike refused by Delta: %s %s %s @ %s: %s" % (side, sym, n, price, why[:200]))


def _flush_refused(self):
    items, self._refused = getattr(self, "_refused", []), []
    if not items:
        return
    seen = getattr(self, "_refused_seen", None)
    if seen is None:
        seen = self._refused_seen = set()
    night = self.S.get("exp")
    new, done = [], set()
    for sym, side, n, price, why in items:
        k = (night, sym, why[:60])
        if k in seen or k in done:
            continue
        done.add(k); new.append((sym, side, n, price, why))
    seen |= done
    if new:
        self.notify("%s STRIKE REFUSED by Delta" % self.lab,
                    "Delta refused new orders on %d strike(s); the bot moved on to the next strikes as set.\\n%s" % (
                        len(new), "\\n".join("%s %s %d contracts @ %s: %s" % (s, sd, n, p, w) for s, sd, n, p, w in new)))


def _wrap_flush(name):
    orig = getattr(LiveNight, name, None)
    if orig is None or getattr(orig, "_rf", False):
        return

    def wrapped(self, *a, **k):
        self._refused = []
        try:
            return orig(self, *a, **k)
        finally:
            self._flush_refused()
    wrapped._rf = True
    wrapped.__name__ = name
    setattr(LiveNight, name, wrapped)


LiveNight._refused_note = _refused_note
LiveNight._flush_refused = _flush_refused
for _n in ("_buy_wings", "sell_smart", "buy_insurance"):
    _wrap_flush(_n)


'''


def main():
    p = os.path.join(H, "nightlive.py")
    s = open(p).read()
    if "_refused_note" in s:
        print("nightlive.py: already patched"); return
    for old, name in ((PLACE_OLD, "order line"), (TAIL_ANCHOR, "end of file")):
        if s.count(old) != 1:
            print("STOP: expected exactly one match for the %s, found %d - NOTHING WRITTEN" % (name, s.count(old))); sys.exit(1)
    if "is_full" not in s.split("class LiveNight")[0]:
        print("STOP: is_full is not imported - NOTHING WRITTEN"); sys.exit(1)
    s = s.replace(PLACE_OLD, PLACE_NEW, 1)
    s = s.replace(TAIL_ANCHOR, TAIL + TAIL_ANCHOR, 1)
    if s.count(CAND_OLD) == 1:
        s = s.replace(CAND_OLD, CAND_NEW, 1); cand = "applied"
    else:
        cand = "NOT applied (line not found %d times) - the hedge list is not filtered by capped strikes" % s.count(CAND_OLD)
    if not os.path.exists(p + ".bak1124r"):
        shutil.copy2(p, p + ".bak1124r")
    open(p + ".tmp", "w").write(s)
    os.replace(p + ".tmp", p)
    print("REFUSEFIX PATCH DONE (capped-strike filter on the hedge list: %s)" % cand)


if __name__ == "__main__":
    main()
