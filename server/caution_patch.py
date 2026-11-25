"""25-Nov-2026 c14: Telegram /caution (nightlive.py + letterbox.py). A manual NEWS-DAY tool, OFF by default, for the night you switch it on only.
The 'flexible exit' Sudip agreed on 24-Nov (back-tests said it loses as a standing rule - so it is never on unless you send /caution on):
every minute, for each open SOLD option: z = distance of BTC to its strike / expected move for the hours left
(expected move = hourly sigma x sqrt(hours left); sigma = the larger of the 7-day volatility and 1.0 x the long-run (365-day) volatility).
 z 3 or more        : nothing (only the usual 10 % resting buy-back)
 z from 2 to 3      : buy it back if its asking price is at most 25 % of its sale price
 z below 2 (or BTC through the strike): at most 40 % of its sale price
Not 23:30-23:59 IST, not while a crash-guard insurance leg is open. Switches itself OFF when the night ends.
/caution (shows) | /caution on | /caution off.  Settings in state/night_live_cfg.json: caution (0/1), caution_z1 2, caution_z2 3, caution_a 0.25, caution_b 0.40, caution_floor 1.0.
Backups: nightlive.py.bak1125c, letterbox.py.bak1125c. Every edit must match exactly once."""
import os, re, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

METHOD = '''    def _caution_exit(self, now, spot, ind):
        """25-Nov-2026 /caution: flexible exit for a news night (see caution_patch.py)"""
        c = self.cfg
        hm = now.hour * 100 + now.minute
        if not c.get("caution") or 2330 <= hm <= 2359 or time.time() - getattr(self, "_cau_t", 0) < float(c.get("caution_every_s", 60)):
            return False
        self._cau_t = time.time()
        if not ind or any(l.get("kind") == "ins" for l in self.open_legs()) or not self.S.get("exp"):
            return False
        hours = (self.S["exp"] - now.timestamp()) / 3600.0
        if hours <= 0.25:
            return False
        sig = max(float(ind.get("hv7") or 0), float(c.get("caution_floor", 1.0)) * float(ind.get("hv365") or 0))
        if sig <= 0 or spot <= 0:
            return False
        move = sig / (8760.0 ** 0.5) * (hours ** 0.5)
        z1, z2, a, b = float(c.get("caution_z1", 2)), float(c.get("caution_z2", 3)), float(c.get("caution_a", 0.25)), float(c.get("caution_b", 0.40))
        done = False
        for l in [x for x in self.open_legs() if x["dir"] == "S" and x.get("kind") != "ins"]:
            thru = (spot <= l["strike"]) if l["side"] == "PE" else (spot >= l["strike"])
            z = 0.0 if thru else abs(l["strike"] - spot) / spot / move
            if z >= z2:
                continue
            lim = (a if z >= z1 else b) * float(l["entry"])
            try:
                ask = float(self.cl.ticker(l["sym"]).get("ask") or 0)
            except Exception:
                continue
            if not (0 < ask <= lim):
                continue
            self.notify("%s CAUTION exit %s" % (self.lab, l["sym"]),
                        "BTC is %.1f normal moves from the strike (%.1f hours left); the option asks %.1f = %.0f %% of its sale price %.1f (limit %.0f %%). Buying it back." % (
                            z, hours, ask, ask / float(l["entry"]) * 100, float(l["entry"]), lim / float(l["entry"]) * 100))
            if self._close(now, spot, l, None, "CAUTION") is not None:
                done = True
        return done

'''

TG = '''def caution(a):
    """25-Nov-2026: /caution | /caution on | /caution off  (one night only, clears itself)"""
    p = os.path.join(HOME, "state", "night_live_cfg.json")
    c = night_cfg()
    if not a:
        return ("CAUTION is %s. %s" % ("ON for this night" if c.get("caution") else "OFF",
                "Buys back a sold option early when BTC is near its strike and the price has dropped to 25-40 %% of the sale price. Send /caution on or /caution off."))
    if a == ["on"]:
        c["caution"] = 1
        jsave(p, c)
        return "CAUTION is ON for this night only (it switches itself off when the night ends). Needs the position open or the 23:30 sale done; not active 23:30-23:59 IST."
    if a == ["off"]:
        c["caution"] = 0
        jsave(p, c)
        return "CAUTION is OFF."
    return "REFUSED: send /caution on, /caution off or /caution"


'''

NL_EDITS = [
    ('juice=0.0, juice_once=0,', 'juice=0.0, caution=0, caution_z1=2.0, caution_z2=3.0, caution_a=0.25, caution_b=0.40, caution_floor=1.0, caution_every_s=60, juice_once=0,'),
    ('(1.1 if why == "JUICE" else self.cfg["bb_cap"])', '(1.1 if why in ("JUICE", "CAUTION") else self.cfg["bb_cap"])'),
]
RX_HOOK = r'(\n( +)changed \|= self\._juice_exit\(now, spot\)\n)'
RX_METHOD = r'(\n    def _juice_exit\(self, now, spot\):)'
RX_FIN = r'(\n( +)Night\._finish\(self, now, why\)\n)'
LB_EDITS = [
    ('"/exit", "/takeprofit", "/install"', '"/exit", "/takeprofit", "/caution", "/install"'),
    ('    ("takeprofit", ', '    ("caution", "News-day exit for this night only: /caution on, /caution off"),\n    ("takeprofit", '),
    ('def telegram(text, st):\n', TG + 'def telegram(text, st):\n'),
    ('    if c == "/takeprofit":\n', '    if c == "/caution":\n        return caution(a)\n    if c == "/takeprofit":\n'),
]


def one(s, old, new, what):
    if s.count(old) != 1:
        print("STOP: expected exactly one match for '%s', found %d - NOTHING WRITTEN" % (what, s.count(old)))
        sys.exit(1)
    return s.replace(old, new)


def rx1(s, rx, rep, what):
    if len(re.findall(rx, s)) != 1:
        print("STOP: expected exactly one match for '%s', found %d - NOTHING WRITTEN" % (what, len(re.findall(rx, s))))
        sys.exit(1)
    return re.sub(rx, rep, s, count=1)


def main():
    pl, pn = os.path.join(H, "letterbox.py"), os.path.join(H, "nightlive.py")
    sl, sn = open(pl).read(), open(pn).read()
    if "def takeprofit(" not in sl or "juice_once" not in sn:
        print("STOP: install /takeprofit (c13) first - NOTHING WRITTEN")
        sys.exit(1)
    nl = ln = None
    if "_caution_exit" not in sn:
        nl = sn
        for old, new in NL_EDITS:
            nl = one(nl, old, new, old[:40])
        nl = rx1(nl, RX_HOOK, lambda m: m.group(1) + m.group(2) + 'changed |= self._caution_exit(now, spot, ind)\n', "hook")
        nl = rx1(nl, RX_METHOD, lambda m: "\n" + METHOD.rstrip("\n") + "\n" + m.group(1), "method")
        nl = rx1(nl, RX_FIN, lambda m: '\n' + m.group(2) + 'try:                                        # 25-Nov-2026: /caution is for one night only\n'
                 + m.group(2) + '    if cfg().get("caution"):\n'
                 + m.group(2) + '        put_cfg(caution=0)\n'
                 + m.group(2) + '        self.notify("%s caution switched off" % self.lab, "the night ended - /caution is OFF again")\n'
                 + m.group(2) + 'except Exception as e:\n'
                 + m.group(2) + '    self.log("caution clear failed: %s" % e)' + m.group(1), "finish")
    if "def caution(" not in sl:
        ln = sl
        for old, new in LB_EDITS:
            ln = one(ln, old, new, old[:40])
    if nl is None and ln is None:
        print("already patched")
        return
    for p, n in ((pl, ln), (pn, nl)):
        if n is not None:
            if not os.path.exists(p + ".bak1125c"):
                shutil.copy2(p, p + ".bak1125c")
            open(p + ".tmp", "w").write(n)
            os.replace(p + ".tmp", p)
    print("CAUTION PATCH DONE")


if __name__ == "__main__":
    main()
