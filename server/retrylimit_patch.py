"""25-Nov-2026 c12: time-based limit for the RETRY hedge + 25 % buy-back of a decayed sold option (Sudip's rule, back-tested 25-Nov).

Only the hedge RETRY changes (the 5-minute tries after the 23:30 sale could not buy the far option).
Today  : the retry buys the far option when its ask is <= 30 % (put) / 50 % (call) of the SALE price.
After  : the retry buys when its ask is <= a share of what the sold option costs to buy back NOW. The share rises through the night:
         30 % (11 h or more left), 40 % (8 h), 50 % (5 h), 60 % (2 h), 75 % (less than 2 h).  Setting retry_tab (hours:share, ...).
         If no hedge was bought for a sold option (nothing partly hedged, no crash-guard insurance) and its buy-back price has fallen to
         25 % of its sale price (setting retry_bb), the sold option is bought back: no more risk on that side.
Untouched: the sale-time hedge and its ceiling, the crash guard, the sizing, the 10 % resting buy-back, the 17:20 exit.
Settings in state/night_live_cfg.json (all optional): retry_lim (1 on / 0 off = old ceiling), retry_tab, retry_bb (0 = no buy-back),
retry_capmax (0 = no cap; else the retry hedge may not cost more than this share of the SALE price).
A Telegram/e-mail message tells every refusal (once per limit step) and every buy-back."""
import os, re, sys, shutil

H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

HELPERS = '''    def _retry_lim(self, tl_h):
        """25-Nov-2026: share of the sold option's price NOW that a retry hedge may cost, by hours left (retry_tab 'hours:share,...')"""
        tab = []
        for part in str(self.cfg.get("retry_tab") or "").split(","):
            try:
                h, f = part.split(":")
                tab.append((float(h), float(f)))
            except Exception:
                pass
        tab.sort(reverse=True)
        for h, f in tab:
            if tl_h >= h:
                return f
        return tab[-1][1] if tab else 0.0

    def _retry_top(self, now, s, top):
        """25-Nov-2026: ceiling for a RETRY hedge = limit share x what the sold option costs to buy back now (else the old ceiling)"""
        try:
            if not float(self.cfg.get("retry_lim", 0) or 0) or not self.S.get("exp"):
                return top
            c0 = getattr(self, "_rt_px", None)
            if c0 and c0[0] == s["sym"] and time.time() - c0[1] < 20:
                cur = c0[2]
            else:
                cur = float(self.cl.ticker(s["sym"]).get("ask") or 0)
                self._rt_px = (s["sym"], time.time(), cur)
            if cur <= 0:
                return top
            tl = (self.S["exp"] - now.timestamp()) / 3600.0
            lim = self._retry_lim(tl)
            if lim <= 0:
                return top
            new = lim * cur
            cm = float(self.cfg.get("retry_capmax", 0) or 0)
            if cm > 0:
                new = min(new, cm * float(s["entry"]))
            self._rt_ctx = dict(sym=s["sym"], cur=cur, lim=lim, tl=tl)
            return new
        except Exception as e:
            self.log("retry limit failed, old ceiling used: %s" % e)
            return top

    def _rt_note(self, s, o, ask, top):
        """tell a refused retry hedge once per limit step"""
        c = getattr(self, "_rt_ctx", None)
        if not c or c.get("sym") != s["sym"]:
            return
        key = "%s|%.2f" % (s["sym"], c["lim"])
        told = self.S.setdefault("rt_told", [])
        if key in told:
            return
        told.append(key)
        del told[:-60]
        self.notify("%s RETRY HEDGE REFUSED for %s" % (self.lab, s["sym"]),
                    "far option %s asks %.1f; the limit is %.1f (%.0f %% of the %.1f it costs to buy the sold option back now, %.1f h left)" % (
                        o["sym"], ask, top, c["lim"] * 100, c["cur"], c["tl"]))

    def _retry_buyback(self, now, spot, todo):
        """25-Nov-2026: no hedge for a sold option and its buy-back price is down to retry_bb x its sale price -> buy it back"""
        f = float(self.cfg.get("retry_bb", 0) or 0)
        if f <= 0 or not float(self.cfg.get("retry_lim", 0) or 0):
            return False
        done = False
        for s0 in todo:
            leg = next((l for l in self.S["legs"] if l["id"] == s0["id"]), None)
            if not leg or leg["closed"] or leg["dir"] != "S" or leg.get("kind") == "ins":
                continue
            if sum(l["qty"] for l in self.S["legs"] if l.get("kind") == "wing" and l.get("cover") == leg["id"]) > 1e-9:
                continue
            if any(l.get("kind") == "ins" and l["side"] == leg["side"] for l in self.open_legs()):
                continue
            try:
                cur = float(self.cl.ticker(leg["sym"]).get("ask") or 0)
            except Exception:
                continue
            if not (0 < cur <= f * float(leg["entry"])):
                continue
            pnl = self._close(now, spot, leg, None, "BB25")
            if pnl is not None:
                done = True
                self.notify("%s RETRY BUY-BACK %s" % (self.lab, leg["sym"]),
                            "no hedge passed the limit and the sold option is down to %.1f (%.0f %% of its sale price %.1f): bought back, no risk left on this side" % (
                                cur, cur / float(leg["entry"]) * 100, float(leg["entry"])))
        return done

'''

EDITS = [
    # (regex, replacement, what)
    (r'(wing_retry_s=300,)( juice=0\.0,)',
     r'\1 retry_lim=1, retry_tab="11:0.30,8:0.40,5:0.50,2:0.60,0:0.75", retry_bb=0.25, retry_capmax=0.0,\2',
     "defaults"),
    (r'(\n( +)top = \(P\.get\("wing_max_put", 0\.3\) if s\["side"\] == "PE" else P\["wing_max"\]\) \* s\["entry"\][^\n]*\n)',
     lambda m: m.group(1) + m.group(2) + 'if getattr(self, "_wing_quiet", False):\n' + m.group(2) + '    top = self._retry_top(now, s, top)\n',
     "retry ceiling"),
    (r'(\n( +)why = "too costly \(ask %\.1f against a ceiling of %\.1f\)" % \(t\["ask"\], top\)\n)',
     lambda m: m.group(1) + m.group(2) + 'if getattr(self, "_wing_quiet", False):\n' + m.group(2) + '    self._rt_note(s, o, t["ask"], top)\n',
     "refusal message"),
    (r'(\n( +)finally:\n +self\._wing_quiet = False\n)( +)return len\(self\.S\["legs"\]\) != n0\n',
     lambda m: m.group(1) + m.group(3) + 'ch0 = len(self.S["legs"]) != n0\n' + m.group(3) + 'bb0 = self._retry_buyback(now, spot, todo)\n' + m.group(3) + 'return ch0 or bb0\n',
     "buy-back call"),
    (r'(\n    def _wing_retry\(self, now, spot\):)',
     lambda m: "\n" + HELPERS.rstrip("\n") + "\n" + m.group(1),
     "helpers"),
]


def patch(s):
    if "_retry_top" in s:
        return None
    for rx, rep, what in EDITS:
        found = re.findall(rx, s)
        if len(found) != 1:
            print("STOP: expected exactly one match for '%s', found %d - NOTHING WRITTEN" % (what, len(found)))
            sys.exit(1)
        s = re.sub(rx, rep, s, count=1)
    return s


def main():
    p = os.path.join(H, "nightlive.py")
    s = open(p).read()
    if "_wing_retry" not in s:
        print("STOP: wing retry is not installed - NOTHING WRITTEN")
        sys.exit(1)
    new = patch(s)
    if new is None:
        print("nightlive.py: already patched")
        return
    if not os.path.exists(p + ".bak1125r"):
        shutil.copy2(p, p + ".bak1125r")
    open(p + ".tmp", "w").write(new)
    os.replace(p + ".tmp", p)
    print("RETRY LIMIT PATCH DONE")


if __name__ == "__main__":
    main()
