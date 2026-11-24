#!/usr/bin/env python3
"""topupside_patch (c04, 24-Nov-2026, Sudip 13:09 "one side must not suffer for the other side").
Top-up to the big base is now decided SIDE BY SIDE (put side, call side separately):
 - a side gets its extra as soon as every far option (hedge) of THAT side is bought, within 1 hour of that side's first sale;
 - a side whose hedge is still missing after 1 hour gets no extra (as before) - but it no longer blocks the other side.
Unchanged: 1-hour window, once a night per side, extra = big base / small base - 1, BTC not past the strike and strike still >= half its
first distance, bid >= 80 % of the first sale price and >= the floor, NO top-up on either side once crash-guard insurance is bought.
Replaces only the body of _topup in nightlive.py. Must match exactly once, else NOTHING is written. Backup nightlive.py.bak1124s"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
START = "    def _topup(self, now, spot, ch, today):\n"
END = "    def step(self, now, spot, ch, ind, stopped=False):\n"
NEW = '''    def _topup(self, now, spot, ch, today):
        """24-Nov-2026 side by side: each side gets its extra once ITS far options are bought within 1 hour (see topupside_patch)"""
        S = self.S
        night = S.get("night")
        if not night or S.get("topup_night") == night:
            return False
        big, base = float(self.cfg.get("base_big") or 0), float(self.base)
        if big <= base + 1e-9:
            return False
        sold = [l for l in self.open_legs() if l["dir"] == "S" and l.get("kind") != "ins"]
        if not sold:
            return False
        if any(l.get("kind") == "ins" for l in self.open_legs()):
            S["topup_night"] = night
            self.log("%s no top-up tonight: crash guard insurance bought" % self.lab)
            return True
        td = S.get("topup_sides")
        if not isinstance(td, dict) or td.get("night") != night:
            td = S["topup_sides"] = {"night": night, "sides": []}
        f = big / base - 1.0
        s0 = float(S.get("sale_spot") or spot)
        changed, t_first = False, None
        for side in sorted(set(l["side"] for l in sold)):
            ss = [l for l in sold if l["side"] == side]
            t0 = min(dt.datetime.fromisoformat(l["t"]) for l in S["legs"] if l["dir"] == "S" and l.get("kind") != "ins" and l["side"] == side)
            t_first = t0 if t_first is None else min(t_first, t0)
            if side in td["sides"]:
                continue
            late = (now - t0).total_seconds() > 3600
            covered = all(sum(w["qty"] for w in S["legs"] if w.get("kind") == "wing" and w.get("cover") == l["id"] and not w["closed"]) >= l["qty"] - 1e-9 for l in ss)
            if late:
                td["sides"].append(side); changed = True
                if not covered:
                    self.log("%s no top-up on the %s side tonight: far options not all bought within 1 hour" % (self.lab, side))
                continue
            if not covered:
                continue
            td["sides"].append(side); changed = True
            groups = {}
            for l in ss:
                groups.setdefault((l["set"], l["sym"]), []).append(l)
            notes = []
            for (key, sym), ls in groups.items():
                l = ls[0]
                q = sum(x["qty"] for x in ls)
                entry = sum(x["entry"] * x["qty"] for x in ls) / q
                extra = int(q * f / C + 1e-9) * C
                if extra < C - 1e-9:
                    continue
                o = next((c for c in ch if c["sym"] == sym), None)
                if not o:
                    notes.append("%s: not in the chain" % sym); continue
                past = (spot <= l["strike"]) if l["side"] == "PE" else (spot >= l["strike"])
                d0, d1 = abs(l["strike"] - s0), abs(l["strike"] - spot)
                if past or d1 < 0.5 * d0:
                    notes.append("%s: BTC too close to the strike (%.0f now, %.0f at the sale)" % (sym, d1, d0)); continue
                if float(o.get("bid") or 0) < max(0.8 * entry, MIN_BID):
                    notes.append("%s: bid %.1f below 80 %% of %.1f or the floor" % (sym, float(o.get("bid") or 0), entry)); continue
                leg = self._open(now, spot, key, l["kind"], l["side"], o, round(extra, 3), "S", "top-up to big base %.2f" % big)
                notes.append("%s: %s %.3f" % (sym, "sold extra" if leg else "extra not filled", extra))
            self.notify("%s TOP-UP to big base %.2f (%s side)" % (self.lab, big, "put" if side == "PE" else "call"), "; ".join(notes) or "nothing to add")
        if t_first is not None and (now - t_first).total_seconds() > 3600 and all(l["side"] in td["sides"] for l in sold):
            S["topup_night"] = night; changed = True
        return changed

'''


def main():
    p = os.path.join(H, "nightlive.py")
    s = open(p, encoding="utf-8").read()
    if "topup_sides" in s:
        print("already applied"); return
    if s.count(START) != 1:
        print("STOP: _topup found %d times - NOTHING WRITTEN" % s.count(START)); sys.exit(1)
    a = s.index(START); b = s.find(END, a)
    if b < 0 or "def " in s[a + len(START):b].replace("def _topup", ""):
        print("STOP: the end of _topup was not found cleanly - NOTHING WRITTEN"); sys.exit(1)
    s = s[:a] + NEW + s[b:]
    shutil.copy2(p, p + ".bak1124s")
    open(p + ".tmp", "w", encoding="utf-8").write(s); os.replace(p + ".tmp", p)
    print("TOPUPSIDE PATCH DONE")


if __name__ == "__main__":
    main()
