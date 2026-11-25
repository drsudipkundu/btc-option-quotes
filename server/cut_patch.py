"""26-Nov-2026 c17: Telegram /cut = manual force exit of ANY side, ANY quantity of the night sale (nightlive.py + letterbox.py).
Purpose (Sudip 26-Nov): raise money for the ladder after a deep fall - square off the minimum needed by hand.
  /cut                      shows what is open on each side (sold options and far hedge)
  /cut put 0.1              asks you to confirm; /cut put 0.1 yes (within 3 minutes) queues it.  put | call, quantity in BTC with a decimal point (0.1 = 100 contracts) or  all
  /cut put 0.1 hedge        same, and the far option (hedge) is sold in proportion too - only if it is worth selling (cut_hedge_min 0.5 USD)
  /cut cancel               withdraw a queued request
The bot does it within a minute (a request made 23:30-23:59 waits until 00:00; a request older than 50 minutes lapses).
Which legs: the sold option with the biggest loss is bought back first (ask minus sale price), then the next. Buy-back is a reduce-only order that takes the book up to
cut_cap (2.0) x the ask. The resting 10 % buy-back is cancelled and put back on what is left.
Hedge (Sudip's rule): by default the far option STAYS (in a crash it has gained value and is insurance; it blocks no money). With the word  hedge  it is sold in proportion.
After a cut there is no top-up that night. Cut quantity is booked as EXIT-CUT (sold option) and EXIT-CUTHEDGE (far option) rows.
Backups: nightlive.py.bak1126, letterbox.py.bak1126. Every edit must match exactly once."""
import os, re, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

METHODS = '''    def _avail(self):
        """USD available in the wallet now (read only); None if it cannot be read"""
        try:
            if hasattr(self.cl, "_p"):
                for b in (self.cl._p("GET", "/v2/wallet/balances").get("result") or []):
                    if b.get("asset_symbol") in ("USD", "USDT"):
                        return float(b.get("available_balance") or 0)
        except Exception:
            pass
        return None

    def _cut_book(self, now, leg, f, avg, fe, event, note):
        """book f contracts closed at avg on a leg (sold option: bought back; far option: sold) - same bookkeeping as _close"""
        part = f * C
        share = part / leg["qty"]
        pnl = ((leg["entry"] - avg) if leg["dir"] == "S" else (avg - leg["entry"])) * part - leg["fee"] * share - fe
        self.S["total_pnl"] += pnl
        if round(part, 6) >= round(leg["qty"], 6) - 1e-9:
            leg["closed"], leg["exit"], leg["pnl"] = True, avg, pnl + leg.get("pnl_part", 0.0)
        else:
            leg["qty"] = round(leg["qty"] - part, 3)
            leg["fee"] -= leg["fee"] * share
            leg["pnl_part"] = leg.get("pnl_part", 0.0) + pnl
        self.row(now, event, dict(leg, qty=round(part, 3)), avg, fe, pnl, note)
        self.save()
        return pnl

    def _cut_leg(self, now, spot, leg, n):
        """buy back n contracts of a sold option now (limit cut_cap x the ask); returns (contracts filled, pnl)"""
        n = min(int(n), int(round(leg["qty"] / C)))
        if n <= 0:
            return 0, 0.0
        if leg.get("tp_oid"):
            self._tp_cancel(now, leg)
            if leg["closed"]:
                return 0, 0.0
            n = min(n, int(round(leg["qty"] / C)))
        f, pnl = 0, 0.0
        try:
            t = self.cl.ticker(leg["sym"])
            if t["ask"] > 0:
                f, avg, fe = self._sweep(leg["sym"], "buy", n, tick_round(t["ask"] * float(self.cfg.get("cut_cap", 2.0)), t["tick"] or 0.5, False), True, self.cfg["fill_wait_s"])
                if f:
                    pnl = self._cut_book(now, leg, f, avg, fe, "EXIT-CUT", "manual /cut")
                    self.notify("%s CUT %s %d contracts @ %.1f" % (self.lab, leg["sym"], f, avg), "pnl %.2f USD (sold @ %.1f)" % (pnl, leg["entry"]))
        finally:
            if not leg["closed"]:
                leg["tp_oid"], leg["tp_seen"], leg["tp_try"] = None, 0, 0
                self._tp_place(leg)
        return f, pnl

    def _cut_wing(self, now, spot, w, n):
        """sell n contracts of a far option if it is worth it (bid x quantity at least cut_hedge_min USD); returns (contracts filled, pnl)"""
        n = min(int(n), int(round(w["qty"] / C)))
        if n <= 0 or w["closed"]:
            return 0, 0.0
        t = self.cl.ticker(w["sym"])
        if t["bid"] <= 0 or t["bid"] * n * C < float(self.cfg.get("cut_hedge_min", 0.5)):
            return 0, 0.0
        floor = t["tick"] or 0.5
        intr = max(0.0, w["strike"] - spot) if w["side"] == "PE" else max(0.0, spot - w["strike"])
        floor = max(floor, tick_round(0.8 * intr, floor, True))
        f, avg, fe = self._sweep(w["sym"], "sell", n, floor, True, self.cfg["fill_wait_s"])
        if not f:
            return 0, 0.0
        pnl = self._cut_book(now, w, f, avg, fe, "EXIT-CUTHEDGE", "far option sold with /cut hedge")
        self.notify("%s CUT hedge %s %d contracts @ %.1f" % (self.lab, w["sym"], f, avg), "pnl %.2f USD (bought @ %.1f)" % (pnl, w["entry"]))
        return f, pnl

    def _cut_exec(self, now, spot):
        """26-Nov-2026 c17: do a /cut request from Telegram (see cut_patch.py)"""
        req = self.cfg.get("cut_req")
        if not req:
            return False
        hm = now.hour * 100 + now.minute
        if 2330 <= hm <= 2359:
            return False                                   # waits until 00:00 (sale and top-up window)
        try:
            put_cfg(cut_req=None)                          # cleared first: a request can never run twice
        except Exception as e:
            self.log("cut request not cleared, not run: %s" % e)
            return False
        nm = "put" if req.get("side") == "PE" else "call"
        if time.time() - float(req.get("t", 0)) > 3000:
            self.notify("%s CUT request lapsed" % self.lab, "the %s cut was asked more than 50 minutes ago and was not done. Send it again if you still want it." % nm)
            return False
        if self.S.get("halt") or not self.S.get("exp") or now.timestamp() > self.S["exp"] - 300:
            self.notify("%s CUT not done" % self.lab, "no cut while the bot is halted or in the last 5 minutes before expiry.")
            return False
        sold = [l for l in self.open_legs() if l["dir"] == "S" and l.get("kind") != "ins" and l["side"] == req.get("side")]
        if not sold:
            self.notify("%s CUT not done" % self.lab, "no sold %s is open." % nm)
            return False
        tot = sum(int(round(l["qty"] / C)) for l in sold)
        want = tot if float(req.get("qty") or -1) <= 0 else min(tot, int(round(float(req["qty"]) / C)))

        def loss(l):
            try:
                return float(self.cl.ticker(l["sym"]).get("ask") or 0) - l["entry"]
            except Exception:
                return 0.0
        order = sorted(sold, key=lambda l: (-loss(l), -l["id"]))
        before = self._avail()
        left, got, pnl_all, notes, hnotes = want, 0, 0.0, [], []
        for l in order:
            if left <= 0:
                break
            take = min(left, int(round(l["qty"] / C)))
            q0 = l["qty"]
            try:
                f, pnl = self._cut_leg(now, spot, l, take)
            except Exception as e:
                notes.append("%s: error %s" % (l["sym"], str(e)[:80]))
                break
            if f:
                got += f
                left -= f
                pnl_all += pnl
                notes.append("%s %d of %d contracts, pnl %.2f" % (l["sym"], f, take, pnl))
                ws = [w for w in self.S["legs"] if w.get("kind") == "wing" and w.get("cover") == l["id"] and not w["closed"]]
                if req.get("hedge"):
                    for w in ws:
                        keep = 0 if l["closed"] else int(math.ceil(round(l["qty"] * (w["qty"] / q0) / C, 6)))
                        fw, pw = self._cut_wing(now, spot, w, int(round(w["qty"] / C)) - keep)
                        pnl_all += pw
                        hnotes.append("%s: sold %d, kept %.3f BTC" % (w["sym"], fw, w["qty"]) if not w["closed"] else "%s: all sold" % w["sym"])
                elif l["closed"]:
                    for w in ws:
                        w["keep"] = True                   # the far option stays after its sold option is cut (Sudip 26-Nov)
                        hnotes.append("%s kept %.3f BTC (insurance)" % (w["sym"], w["qty"]))
            if f < take:
                notes.append("%s: only %d of %d filled - stopped" % (l["sym"], f, take))
                break
        if got:
            self.S["cut_night"] = self.S.get("night")
        self.save()
        after = self._avail()
        self.notify("%s CUT %s: %d of %d contracts bought back" % (self.lab, nm, got, want),
                    "%s\\nCut pnl incl. far options sold: %.2f USD\\nFar options: %s\\nAvailable money on Delta: %s\\nNo top-up for the rest of this night. The resting 10 %% buy-back stands on what is left." % (
                        "; ".join(notes) or "nothing filled",
                        pnl_all, "; ".join(hnotes) or "none touched (they stay)",
                        "%.2f -> %.2f USD" % (before, after) if before is not None and after is not None else "not read"))
        return True

'''

TG = '''def cutcmd(a, st):
    """26-Nov-2026 c17: /cut | /cut put 0.1 [hedge] [yes] | /cut call all [hedge] [yes] | /cut cancel"""
    p = os.path.join(HOME, "state", "night_live_cfg.json")
    S = night_state()
    legs = [l for l in S.get("legs", []) if not l.get("closed")]
    sold = [l for l in legs if l.get("dir") == "S" and l.get("kind") != "ins"]
    t = [x.lower() for x in a]
    if t == ["cancel"]:
        c = night_cfg()
        c["cut_req"] = None
        jsave(p, c)
        return "CUT request withdrawn."
    if not t:
        if not sold:
            return "CUT: no sold option is open. Usage: /cut put 0.1 (BTC, with a decimal point) or /cut call all; add the word hedge to sell the far option too."
        out = []
        for side, nm in (("PE", "PUT"), ("CE", "CALL")):
            ls = [l for l in sold if l["side"] == side]
            if ls:
                out.append("%s: %s | far option %.3f BTC" % (nm, "; ".join("%s %.3f BTC sold @ %.1f" % (l["sym"], l["qty"], l["entry"]) for l in ls),
                                                           sum(l["qty"] for l in legs if l.get("kind") == "wing" and l.get("side") == side)))
        pend = night_cfg().get("cut_req")
        return ("OPEN NOW\\n" + "\\n".join(out) + ("\\nQUEUED: %s" % pend if pend else "") +
                "\\nCut: /cut put 0.1  or  /cut call all  (then it asks you to confirm). Add  hedge  to sell the far option too; without it the far option stays. /cut cancel withdraws.")
    yes, hedge = "yes" in t, "hedge" in t
    rest = [x for x in t if x not in ("yes", "hedge")]
    side = {"put": "PE", "p": "PE", "pe": "PE", "call": "CE", "c": "CE", "ce": "CE"}.get(rest[0]) if rest else None
    if len(rest) != 2 or side is None or not (rest[1] == "all" or re.fullmatch(r"\\d{1,2}\\.\\d{1,3}", rest[1])):
        return "REFUSED: send /cut put 0.1 or /cut call all (BTC with a decimal point: 0.1 = 100 contracts), optional word hedge, then the same line with yes"
    ls = [l for l in sold if l["side"] == side]
    nm = "put" if side == "PE" else "call"
    if not ls:
        return "REFUSED: no sold %s is open" % nm
    tot = sum(l["qty"] for l in ls)
    q = -1.0 if rest[1] == "all" else float(rest[1])
    if q != -1.0 and q < 0.001 - 1e-9:
        return "REFUSED: smallest cut is 0.001 BTC"
    if q > tot + 1e-9:
        return "REFUSED: only %.3f BTC of the %s is open" % (tot, nm)
    what = " ".join(rest + (["hedge"] if hedge else []))
    use = tot if q < 0 else q
    if not (yes and time.time() - st.get("cut_ask", 0) <= 180 and st.get("cut_what") == what):
        st["cut_ask"], st["cut_what"] = time.time(), what
        return ("CUT asks: buy back %.3f BTC (%d contracts) of the sold %s now, biggest loss first. %s\\nSend  /cut %s yes  within 3 minutes to do it. Anything else = nothing happens."
                % (use, int(round(use / 0.001)), nm, "The far option is sold in proportion if it is worth selling." if hedge else "The far option stays.", what))
    st["cut_ask"] = 0
    c = night_cfg()
    c["cut_req"] = {"side": side, "qty": q, "hedge": 1 if hedge else 0, "t": time.time()}
    jsave(p, c)
    return ("CUT queued: %s %s of the %s, far option %s. The bot does it within a minute (a request made 23:30-23:59 IST waits until 00:00; it lapses after 50 minutes). You get a message when done. /cut cancel withdraws it."
            % ("all" if q < 0 else "%.3f BTC" % q, "(now %.3f BTC)" % tot, nm, "sold in proportion" if hedge else "stays"))


'''

NL_EDITS = [
    ('juice=0.0, size_mult=1.0,', 'juice=0.0, cut_req=None, cut_cap=2.0, cut_hedge_min=0.5, size_mult=1.0,'),
    ('if l.get("kind") != "wing" or any(x["dir"] == "S" and x["side"] == l["side"] for x in self.open_legs()):',
     'if l.get("kind") != "wing" or l.get("keep") or any(x["dir"] == "S" and x["side"] == l["side"] for x in self.open_legs()):'),
    ('if not night or S.get("topup_night") == night:', 'if not night or S.get("topup_night") == night or S.get("cut_night") == night:'),
]
RX_HOOK = r'(\n( +)changed \|= self\.tp_poll\(now\)\n)'
RX_METHOD = r'(\n    def _juice_exit\(self, now, spot\):)'
LB_EDITS = [
    ('"/caution", "/size"', '"/caution", "/cut", "/size"'),
    ('    ("caution", ', '    ("cut", "Force exit by hand: /cut put 0.1, /cut call all, add hedge to sell far option too"),\n    ("caution", '),
    ('def telegram(text, st):\n', TG + 'def telegram(text, st):\n'),
    ('    if c == "/caution":\n', '    if c == "/cut":\n        return cutcmd(a, st)\n    if c == "/caution":\n'),
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
    if "def caution(" not in sl or "_caution_exit" not in sn:
        print("STOP: install /caution (c14) first - NOTHING WRITTEN")
        sys.exit(1)
    nl = ln = None
    if "_cut_exec" not in sn:
        nl = sn
        for old, new in NL_EDITS:
            nl = one(nl, old, new, old[:40])
        nl = rx1(nl, RX_HOOK, lambda m: m.group(1) + m.group(2) + 'changed |= self._cut_exec(now, spot)\n', "hook")
        nl = rx1(nl, RX_METHOD, lambda m: "\n" + METHODS.rstrip("\n") + "\n" + m.group(1), "methods")
    if "def cutcmd(" not in sl:
        ln = sl
        for old, new in LB_EDITS:
            ln = one(ln, old, new, old[:40])
    if nl is None and ln is None:
        print("already patched")
        return
    for p, n in ((pl, ln), (pn, nl)):
        if n is not None:
            if not os.path.exists(p + ".bak1126"):
                shutil.copy2(p, p + ".bak1126")
            open(p + ".tmp", "w").write(n)
            os.replace(p + ".tmp", p)
    print("CUT PATCH DONE")


if __name__ == "__main__":
    main()
