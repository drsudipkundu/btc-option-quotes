#!/usr/bin/env python3
"""flagpaper_patch (18-Nov-2026, Sudip: "1.5x is final", "built and paper run"): two more PAPER copies beside V5A-CG-SL-P.
  v5aslf = V5A-CG-SL-F : trend leg (and its IV boost) x 1.5 when ANY flag is on
  v5aslh = V5A-CG-SL-H : the same, and x 0.5 when NO flag is on
Flags, all read at the sale:  P  premium (bid as % of BTC) in the top 10 % of its last 365 days (state/prem_hist.csv)
                              V  implied volatility of the sold option in the top 20 % of its last 365 days (state/iv_hist.csv)
                              R  4-hour RSI14 agrees with the trend leg: put and RSI >= 60, call and RSI < 40
The opposite leg, strikes, side, slope-half, buy-back and crash guard are unchanged. PAPER ONLY - no order is placed; inactive
unless the copy's name ends with p, f or h, so the live seller's rules (v5asl) are unchanged. Needs richpaper_patch installed.
Run in ~/deltabot. Every edit must match exactly once, otherwise NOTHING is written. Backups: <file>.bak1118f"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))

NEWFN = '''    # ---- size flags: paper copies whose name ends with p (premium only), f (any flag x1.5) or h (any flag x1.5, no flag x0.5)
    def _hist_line(self, fname, today, val, pct, sym):
        """state/<fname> holds one value per night. Returns (line or None, nights used): the pct-quantile of the last 365 days
        before today (None with fewer than RICH_MIN_N nights). Adds today's value once."""
        path = os.path.join(self.home, "state", fname)
        rows = []
        try:
            for r in csv.reader(open(path)):
                if len(r) >= 2 and r[0][:2] == "20":
                    rows.append((r[0], float(r[1])))
        except Exception:
            pass
        lo = (dt.datetime.strptime(today, "%Y-%m-%d") - dt.timedelta(days=365)).strftime("%Y-%m-%d")
        hist = sorted(v for d, v in rows if lo <= d < today)
        thr = None
        if len(hist) >= RICH_MIN_N:
            x = pct * (len(hist) - 1)
            i = int(x)
            thr = hist[i] + (hist[min(i + 1, len(hist) - 1)] - hist[i]) * (x - i)
        if not any(d == today for d, _ in rows):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", newline="") as fh:
                csv.writer(fh).writerow([today, round(val, 4), "delta", sym])
        return thr, len(hist)

    def _rich_qty(self, now, spot, tag, o, qty, ind=None):
        """trend leg only. Returns (quantity, note)."""
        rich, fl = getattr(self, "rich", False), getattr(self, "flags", False)
        if not (rich or fl) or tag != "trend" or not spot or spot <= 0 or o["bid"] <= 0:
            return qty, ""
        today = self.S["night"]
        prem = o["bid"] / spot * 100.0
        thr, n = self._hist_line("prem_hist.csv", today, prem, RICH_PCT, o["sym"])
        P = thr is not None and prem >= thr
        note = "premium %.3f %% of BTC (top-10%% line %s, %d nights) %s" % (prem, "%.3f" % thr if thr is not None else "n/a", n, "ON" if P else "off")
        if rich:
            mult = RICH_MULT if P else 1.0
        else:
            iv = float(o.get("iv") or 0)
            V, tv, nv = False, None, 0
            if iv > 0:
                tv, nv = self._hist_line("iv_hist.csv", today, iv, FLAG_IV_PCT, o["sym"])
                V = tv is not None and iv >= tv
            r = (ind or {}).get("rsi4h")
            R = r is not None and ((o["typ"] == "PE" and r >= RSI_PUT) or (o["typ"] == "CE" and r < RSI_CALL))
            note += "; volatility %.3f (top-20%% line %s, %d nights) %s; 4h RSI %s %s" % (
                iv, "%.3f" % tv if tv is not None else "n/a", nv, "ON" if V else "off",
                "%.1f" % r if r is not None else "n/a", "ON" if R else "off")
            mult = RICH_MULT if (P or V or R) else getattr(self, "noflag_mult", 1.0)
            self.S["flags_night"] = dict(night=today, P=bool(P), V=bool(V), R=bool(R), mult=mult)
        if mult != 1.0:
            qty = qty * mult
            self.S["rich_night"], self.S["rich_mult"] = today, mult
            note += " -> trend leg x %.1f" % mult
            self.notify("%s trend leg x %.1f tonight (paper)" % (self.lab, mult), note)
        self.log("%s %s" % (self.lab, note))
        return qty, note

'''

RSI = '''
def rsi14(closes, n=14):
    """Wilder RSI of the last value; None with too few bars."""
    if len(closes) < 5 * n:
        return None
    up = dn = 0.0
    for k in range(1, n + 1):
        d = closes[k] - closes[k - 1]
        up += max(d, 0.0); dn += max(-d, 0.0)
    up /= n; dn /= n
    for k in range(n + 1, len(closes)):
        d = closes[k] - closes[k - 1]
        up = (up * (n - 1) + max(d, 0.0)) / n
        dn = (dn * (n - 1) + max(-d, 0.0)) / n
    return 100.0 if dn == 0 else 100.0 - 100.0 / (1.0 + up / dn)


class Feed:
'''

def nightlogic(s):
    a = s.index("    # ---- rich-premium size-up")
    b = s.index("    # ---- what the rules want tonight\n")
    if s.count("    # ---- rich-premium size-up") != 1 or s.count("    # ---- what the rules want tonight\n") != 1 or a > b:
        raise ValueError("rich-premium block not found once")
    s = s[:a] + NEWFN + s[b:]
    for old, new in [
        ('"v5aslp": "V5A-CG-SL-P"}', '"v5aslp": "V5A-CG-SL-P", "v5aslf": "V5A-CG-SL-F", "v5aslh": "V5A-CG-SL-H"}\nFLAG_IV_PCT, RSI_PUT, RSI_CALL, NOFLAG_MULT = 0.80, 60.0, 40.0, 0.5   # v5aslf / v5aslh (paper)'),
        ('        self.rich = variant.endswith("p")\n', '        self.rich = variant.endswith("p")\n        self.flags = len(variant) == 6 and variant[-1] in ("f", "h")\n        self.noflag_mult = NOFLAG_MULT if variant.endswith("h") else 1.0\n'),
        ('            rq, rnote = self._rich_qty(now, spot, tag, o, p["qty"])\n', '            rq, rnote = self._rich_qty(now, spot, tag, o, p["qty"], ind)\n'),
        ('        if bq and getattr(self, "rich", False) and S.get("rich_night") == today:\n            bq = bq * RICH_MULT\n',
         '        if bq and (getattr(self, "rich", False) or getattr(self, "flags", False)) and S.get("rich_night") == today:\n            bq = bq * S.get("rich_mult", RICH_MULT)\n'),
    ]:
        if s.count(old) != 1:
            raise ValueError("expected exactly one match, found %d, for: %s" % (s.count(old), old[:90]))
        s = s.replace(old, new)
    return s

SIMPLE = {
 "nightbot.py": [
  ('\nclass Feed:\n', RSI),
  ('''        return sorted(r, key=lambda x: x["time"])

    def chain(self, exp_ts):''', '''        return sorted(r, key=lambda x: x["time"])

    def rsi4h(self, now):
        """RSI14 of the completed 4-hour BTCUSD bars (bars that ended at or before now)."""
        r = self.d.public("/v2/history/candles", {"resolution": "4h", "symbol": "BTCUSD",
                                                  "start": int(now - 60 * 86400), "end": int(now)})["result"]
        cs = sorted([c for c in r if c["time"] + 14400 <= now], key=lambda x: x["time"])
        return rsi14([float(c["close"]) for c in cs])

    def chain(self, exp_ts):'''),
  ('''            self.ind = indicators(self.feed.candles(now_ts), now_ts)
            self.ind_ts = now_ts
''', '''            self.ind = indicators(self.feed.candles(now_ts), now_ts)
            self.ind_ts = now_ts
            if self.ind is not None:
                try:
                    self.ind["rsi4h"] = self.feed.rsi4h(now_ts)
                except Exception as e:
                    self.ind["rsi4h"] = None
                    log.warning("4h RSI not available: %s", e)
'''),
  ('"v5aslj", "v5aslp")]', '"v5aslj", "v5aslp", "v5aslf", "v5aslh")]'),
 ],
 "control.py": [('"v5aslj", "v5aslp", "nlive"', '"v5aslj", "v5aslp", "v5aslf", "v5aslh", "nlive"')],
 "ui.py": [
  ('    "nlive": ("BTC Night Leg LIVE MONEY', '    "v5aslf": ("BTC Night Leg V5A-CG-SL-F (any flag x1.5)", "V5A-CG-SL, but the trend leg is sold 1.5 times when any flag is on: premium in the top 10 % of its last 365 days, implied volatility in the top 20 % of its last 365 days, or the 4-hour RSI agreeing with the trend leg (put and RSI 60 or more, call and RSI under 40). Paper only, added 18-Nov-2026."),\n    "v5aslh": ("BTC Night Leg V5A-CG-SL-H (any flag x1.5, no flag half)", "V5A-CG-SL-F, and the trend leg is sold at half size on nights with no flag. Paper only, added 18-Nov-2026."),\n    "nlive": ("BTC Night Leg LIVE MONEY'),
  ('"v5aslj", "v5aslp", "nlive"):', '"v5aslj", "v5aslp", "v5aslf", "v5aslh", "nlive"):'),
 ],
}


def main():
    out = {}
    try:
        p = os.path.join(H, "nightlogic.py"); s = open(p).read()
        if "v5aslh" in s:
            print("nightlogic.py: already patched")
        elif "v5aslp" not in s:
            print("STOP: richpaper_patch is not installed - NOTHING WRITTEN"); sys.exit(1)
        else:
            out[p] = nightlogic(s)
        for fn, edits in SIMPLE.items():
            p = os.path.join(H, fn); s = open(p).read()
            if "v5aslh" in s:
                print("%s: already patched" % fn); continue
            for old, new in edits:
                if s.count(old) != 1:
                    raise ValueError("%s: expected exactly one match, found %d, for: %s" % (fn, s.count(old), old[:90]))
                s = s.replace(old, new)
            out[p] = s
    except ValueError as e:
        print("STOP: %s\nNOTHING WRITTEN" % e); sys.exit(1)
    for p, s in out.items():
        if not os.path.exists(p + ".bak1118f"):
            shutil.copy2(p, p + ".bak1118f")
        open(p + ".tmp", "w").write(s)
        os.replace(p + ".tmp", p)
    print("FLAG PAPER PATCH DONE (%d files)" % len(out))


if __name__ == "__main__":
    main()
