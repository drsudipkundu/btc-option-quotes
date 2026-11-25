"""25-Nov-2026 c13: Telegram /takeprofit x  (letterbox.py + nightlive.py). Uses the existing, tested 'little premium left' exit (juice).
/takeprofit 80         close the night when 80 % of its premium is earned (THIS night only; the setting clears when the night ends)
/takeprofit 80 always  same, but stays on every night until /takeprofit off
/takeprofit 0          close everything now (the sold options are bought back at the next minute check), sales go on tomorrow
/takeprofit off        switch the rule off     /takeprofit   shows the setting
Allowed 0 to 95. Up to 30 asks for a confirmation (send the same command with 'yes' within 3 minutes).
Not active 23:30-23:59 IST and not while a crash-guard insurance leg is open (the old rule's conditions). Every edit must match exactly once, else nothing is written.
Backups: letterbox.py.bak1125t, nightlive.py.bak1125t"""
import os, re, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

TP_FUNC = '''def takeprofit(a, st):
    """25-Nov-2026: /takeprofit x [always] | /takeprofit off | /takeprofit 0 | /takeprofit"""
    p = os.path.join(HOME, "state", "night_live_cfg.json")
    c = night_cfg()
    j = float(c.get("juice") or 0)
    if not a:
        if not j:
            return "TAKE-PROFIT: off. Send /takeprofit 80 (close this night when 80 % of its premium is earned), /takeprofit 80 always, /takeprofit 0 (close now), /takeprofit off."
        return "TAKE-PROFIT: ON - closes when %s %% of the night's premium is earned (%s). Send /takeprofit off to remove." % (
            "all (close now)" if j >= 5 else "%.0f" % (100 - j * 100), "this night only" if c.get("juice_once") else "every night")
    if a[0] == "off" and len(a) == 1:
        c.update(juice=0.0, juice_once=0, juice_keep=0.0)
        jsave(p, c)
        return "TAKE-PROFIT is OFF."
    if not re.fullmatch(r"\\d{1,2}(\\.\\d)?", a[0]) or len(a) > 3 or (len(a) > 1 and a[1:] not in (["always"], ["yes"], ["always", "yes"])):
        return "REFUSED: send /takeprofit 80 (percent of the premium to earn, 0 to 95), /takeprofit 80 always, /takeprofit 0, /takeprofit off"
    x = float(a[0])
    if x > 95:
        return "REFUSED: 0 to 95 percent"
    always, yes = "always" in a, "yes" in a
    what = " ".join(t for t in a if t != "yes")
    if x <= 30 and not (yes and time.time() - st.get("tp_ask", 0) <= 180 and st.get("tp_what") == what):
        st["tp_ask"], st["tp_what"] = time.time(), what
        return ("TAKE-PROFIT %s asks: %s\\nSend  /takeprofit %s yes  within 3 minutes to do it. Anything else = nothing happens."
                % (a[0], "close the sold options NOW at the market's offers" if x == 0 else "close the night as soon as only %.0f %% of its premium is left to earn" % (100 - x), what))
    st["tp_ask"] = 0
    keep = float(c.get("juice_keep") or 0) if c.get("juice_once") else float(c.get("juice") or 0)
    c.update(juice=1000.0 if x == 0 else round((100.0 - x) / 100.0, 4), juice_once=0 if always else 1, juice_keep=keep)
    jsave(p, c)
    return ("TAKE-PROFIT set: %s. %s It is checked every minute (not 23:30-23:59 IST, and not while a crash-guard insurance leg is open)." % (
        "close the sold options now" if x == 0 else "close the night when %.0f %% of its premium is earned" % x,
        "Every night until /takeprofit off." if always else "This night only; it clears when the night ends."))


'''

LB_EDITS = [
    ('"/exit", "/install", "/orders"', '"/exit", "/takeprofit", "/install", "/orders"'),
    ('    ("exit", "Buy back everything now - asks you to confirm"),\n',
     '    ("exit", "Buy back everything now - asks you to confirm"),\n    ("takeprofit", "Close the night at x% of premium earned: /takeprofit 80, 0 = now, off"),\n'),
    ('def telegram(text, st):\n', TP_FUNC + 'def telegram(text, st):\n'),
    ('    return TG_HELP\n\n\n# ----', '    if c == "/takeprofit":\n        return takeprofit(a, st)\n    return TG_HELP\n\n\n# ----'),
    ('/exit = buy back everything now (asks to confirm) | /install = update', '/exit = buy back everything now (asks to confirm) | /takeprofit 80 = close the night at 80 percent of premium earned | /install = update'),
]

NL_EDITS = [
    ('juice=0.0, juice_every_s=60,', 'juice=0.0, juice_once=0, juice_keep=0.0, juice_every_s=60,'),
]
NL_RX = (r'(\n( +)Night\._finish\(self, now, why\)\n)',
         lambda m: '\n' + m.group(2) + 'try:                                        # 25-Nov-2026: a one-night /takeprofit clears when the night ends\n'
                   + m.group(2) + '    if cfg().get("juice_once"):\n'
                   + m.group(2) + '        put_cfg(juice=float(cfg().get("juice_keep") or 0), juice_once=0)\n'
                   + m.group(2) + '        self.notify("%s take-profit cleared" % self.lab, "the one-night /takeprofit setting ended with the night")\n'
                   + m.group(2) + 'except Exception as e:\n'
                   + m.group(2) + '    self.log("take-profit clear failed: %s" % e)' + m.group(1))


def one(s, old, new, what):
    if s.count(old) != 1:
        print("STOP: expected exactly one match for '%s', found %d - NOTHING WRITTEN" % (what, s.count(old)))
        sys.exit(1)
    return s.replace(old, new)


def main():
    pl, pn = os.path.join(H, "letterbox.py"), os.path.join(H, "nightlive.py")
    sl, sn = open(pl).read(), open(pn).read()
    new_l = new_n = None
    if "def takeprofit(" not in sl:
        new_l = sl
        for old, new in LB_EDITS:
            new_l = one(new_l, old, new, old[:40])
    if "juice_once" not in sn:
        new_n = sn
        for old, new in NL_EDITS:
            new_n = one(new_n, old, new, old[:40])
        if len(re.findall(NL_RX[0], new_n)) != 1:
            print("STOP: expected one Night._finish call, found %d - NOTHING WRITTEN" % len(re.findall(NL_RX[0], new_n)))
            sys.exit(1)
        new_n = re.sub(NL_RX[0], NL_RX[1], new_n, count=1)
    if new_l is None and new_n is None:
        print("already patched")
        return
    for p, s, n in ((pl, sl, new_l), (pn, sn, new_n)):
        if n is not None:
            if not os.path.exists(p + ".bak1125t"):
                shutil.copy2(p, p + ".bak1125t")
            open(p + ".tmp", "w").write(n)
            os.replace(p + ".tmp", p)
    print("TAKEPROFIT PATCH DONE")


if __name__ == "__main__":
    main()
