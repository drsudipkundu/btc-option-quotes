"""25-Nov-2026 c15: Telegram /size x (nightlive.py + letterbox.py): ONE-NIGHT size multiplier, smaller only.
/size 0.5   the next 23:30 sale (and its top-up) is half the usual size; applies to that one night, then goes back to 1 by itself
/size 1  or /size off   back to normal now        /size   shows the setting
Allowed 0.1 to 1 (smaller only - going bigger is the base/ceiling decision, not a one-night word). Legs already open are not changed.
The multiplier acts on the base the rules use (after the slope-half), so the x3 trend leg, the opposite leg and the extra size all shrink together;
the big/small top-up ratio is kept. Settings in state/night_live_cfg.json: size_mult (1 = normal), size_night (the night it was first used; set by the bot).
Backups: nightlive.py.bak1125s, letterbox.py.bak1125s. Every edit must match exactly once."""
import os, re, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

METHODS = '''    def _size_mult(self):
        """25-Nov-2026 /size: the multiplier that counts tonight (1 = normal; an old, unused-by-tonight setting counts as 1)"""
        try:
            m = float(self.cfg.get("size_mult", 1) or 1)
        except Exception:
            return 1.0
        if not (0.0 < m < 1.0):
            return 1.0
        sn = self.cfg.get("size_night")
        if sn and sn != self.S.get("night"):
            return 1.0
        return m

    def size_base(self, ind):
        b = Night.size_base(self, ind)
        night = self.S.get("night")
        try:
            raw = float(self.cfg.get("size_mult", 1) or 1)
            sn = self.cfg.get("size_night")
            if 0.0 < raw < 1.0 and sn and sn != night:
                put_cfg(size_mult=1.0, size_night="")          # it was for an earlier night: used up
                self.cfg = cfg()
                return b
            m = self._size_mult()
            if m < 1.0:
                if not sn:
                    put_cfg(size_night=night)                 # tonight is the night that uses it
                    self.cfg = cfg()
                b = max(C, round(round(b * m / C) * C, 3))
        except Exception as e:
            self.log("size multiplier failed, normal size used: %s" % e)
        return b

'''

TG = '''def sizecmd(a):
    """25-Nov-2026: /size | /size 0.5 | /size 1 | /size off  (one night, smaller only)"""
    p = os.path.join(HOME, "state", "night_live_cfg.json")
    c = night_cfg()
    base = float(c.get("base") or 0)
    m = float(c.get("size_mult", 1) or 1)
    if not a:
        if 0 < m < 1:
            return "SIZE: next 23:30 sale at %.2f x the usual (base %.3f -> %.3f), that one night only. /size 1 cancels." % (m, base, base * m)
        return "SIZE: normal. Send /size 0.5 for half size at the next 23:30 sale (one night only), 0.1 to 1."
    if a in (["1"], ["off"]):
        c.update(size_mult=1.0, size_night="")
        jsave(p, c)
        return "SIZE is normal (x1)."
    if len(a) != 1 or not re.fullmatch(r"0?\\.\\d{1,2}", a[0]):
        return "REFUSED: send /size 0.5 (a number from 0.1 to 1: smaller only), /size 1 or /size off, or /size"
    x = float(a[0])
    if not (0.1 <= x < 1.0):
        return "REFUSED: 0.1 to 1 only (smaller than usual). To go bigger change the base or the ceiling."
    c.update(size_mult=x, size_night="")
    jsave(p, c)
    op = open_legs()
    return ("SIZE set: the next 23:30 sale at %.2f x the usual (base %.3f -> %.3f; the trend leg x3 etc. shrink together; the top-up keeps its ratio). One night only, then normal again.%s"
            % (x, base, base * x, " Open legs now are NOT changed." if op else ""))


'''

NL_EDITS = [
    ('juice=0.0, caution=0,', 'juice=0.0, size_mult=1.0, size_night="", caution=0,'),
]
RX_METHOD = r'(\n    def _topup\(self, now, spot, ch, today\):)'
LB_EDITS = [
    ('"/exit", "/takeprofit", "/caution", "/install"', '"/exit", "/takeprofit", "/caution", "/size", "/install"'),
    ('    ("caution", ', '    ("size", "Size of the NEXT night only: /size 0.5 (0.1 to 1), /size 1 = normal"),\n    ("caution", '),
    ('def telegram(text, st):\n', TG + 'def telegram(text, st):\n'),
    ('    if c == "/caution":\n', '    if c == "/size":\n        return sizecmd(a)\n    if c == "/caution":\n'),
]


def one(s, old, new, what):
    if s.count(old) != 1:
        print("STOP: expected exactly one match for '%s', found %d - NOTHING WRITTEN" % (what, s.count(old)))
        sys.exit(1)
    return s.replace(old, new)


def main():
    pl, pn = os.path.join(H, "letterbox.py"), os.path.join(H, "nightlive.py")
    sl, sn = open(pl).read(), open(pn).read()
    if "def caution(" not in sl or "_caution_exit" not in sn:
        print("STOP: install /caution (c14) first - NOTHING WRITTEN")
        sys.exit(1)
    nl = ln = None
    if "_size_mult" not in sn:
        nl = sn
        for old, new in NL_EDITS:
            nl = one(nl, old, new, old[:40])
        if len(re.findall(RX_METHOD, nl)) != 1:
            print("STOP: expected one _topup definition, found %d - NOTHING WRITTEN" % len(re.findall(RX_METHOD, nl)))
            sys.exit(1)
        nl = re.sub(RX_METHOD, lambda m: "\n" + METHODS.rstrip("\n") + "\n" + m.group(1), nl, count=1)
    if "def sizecmd(" not in sl:
        ln = sl
        for old, new in LB_EDITS:
            ln = one(ln, old, new, old[:40])
    if nl is None and ln is None:
        print("already patched")
        return
    for p, n in ((pl, ln), (pn, nl)):
        if n is not None:
            if not os.path.exists(p + ".bak1125s"):
                shutil.copy2(p, p + ".bak1125s")
            open(p + ".tmp", "w").write(n)
            os.replace(p + ".tmp", p)
    print("SIZE PATCH DONE")


if __name__ == "__main__":
    main()
