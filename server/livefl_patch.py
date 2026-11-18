#!/usr/bin/env python3
"""livefl_patch (18-Nov-2026, Sudip: upgrade the live seller to the size flags after tonight's paper run).
Gives the LIVE seller (nightlive.py, rule v5asl) the same size flags as paper copies F and H, behind a switch in state/night_live_cfg.json:
   flagmode = "off" (default; live sells exactly as before) | "f" (any flag -> trend leg and its boost x1.5) | "h" (also x0.5 when no flag)
Flags (read at the sale, no look-ahead): P premium top 10 % of 365 d; V implied vol top 20 % of 365 d; R 4h RSI agrees with the trend leg.
Also: autosize guard limits become 5 x base per order / 12 x base open while flagmode is f or h (8x/3x when off); needs 4.5x per order, 5.5 units open + hedge.
Needs flagpaper_patch installed (nightlogic._rich_qty). Run in ~/deltabot. Every edit must match once or NOTHING is written. Backups .bak1118l"""
import os, sys, shutil
H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
EDITS = {
 "nightlive.py": [
  ('        self.jump = False                      # strike jump is paper-only for now (15-Nov-2026)\n',
   '        self.jump = False                      # strike jump is paper-only for now (15-Nov-2026)\n        self.rich = False\n        self.flags = False\n        self.noflag_mult = 1.0\n'),
  ('            S.setdefault("plan", {})[tag] = round(p["qty"], 3)\n            changed = True\n            self._open(now, spot, tag, p["kind"], p["side"], o, round(p["qty"], 3), "S")\n',
   '            fm = str(cfg().get("flagmode", "off")).lower()\n            self.flags = fm in ("f", "h")\n            self.noflag_mult = NL.NOFLAG_MULT if fm == "h" else 1.0\n            try:\n                rq, rnote = self._rich_qty(now, spot, tag, o, p["qty"], ind)\n            except Exception as e:\n                rq, rnote = p["qty"], ""\n                self.log("size flags failed, normal size used: %s" % e)\n            S.setdefault("plan", {})[tag] = round(rq, 3)\n            changed = True\n            self._open(now, spot, tag, p["kind"], p["side"], o, round(rq, 3), "S", rnote)\n'),
  ('        bq = self.boost_qty(ind)\n        if bq and "boost" not in S["fired"]:\n            t = [l for l in self.open_legs() if l["set"] == "trend"',
   '        bq = self.boost_qty(ind)\n        if bq and self.flags and S.get("rich_night") == today:\n            bq = bq * S.get("rich_mult", 1.0)\n        if bq and "boost" not in S["fired"]:\n            t = [l for l in self.open_legs() if l["set"] == "trend"'),
  ('                    ind, ind_t = indicators(feed.candles(now_ts), now_ts), now_ts\n',
   '                    ind, ind_t = indicators(feed.candles(now_ts), now_ts), now_ts\n                    if ind is not None and str(cfg().get("flagmode", "off")).lower() in ("f", "h"):\n                        try:\n                            ind["rsi4h"] = feed.rsi4h(now_ts)\n                        except Exception as e:\n                            ind["rsi4h"] = None\n                            log.warning("4h RSI not available: %s", e)\n'),
 ],
 "nightlogic.py": [
  ('self.notify("%s trend leg x %.1f tonight (paper)" % (self.lab, mult), note)',
   'self.notify("%s trend leg x %.1f tonight%s" % (self.lab, mult, "" if str(self.lab).startswith("NLIVE") else " (paper)"), note)'),
 ],
 "autosize.py": [
  ('    return dict(max_order_btc=round(max(0.05, 3 * base), 3), max_open_btc=round(max(0.15, 8 * base), 3))\n',
   '    try:\n        fm = str(jload(os.path.join(HOME, "state", "night_live_cfg.json")).get("flagmode", "off")).lower()\n    except Exception:\n        fm = "off"\n    a, b = (5, 12) if fm in ("f", "h") else (3, 8)\n    return dict(max_order_btc=round(max(0.05, a * base), 3), max_open_btc=round(max(0.15, b * base), 3))\n'),
 ],
}
def main():
    texts = {}
    for f, eds in EDITS.items():
        s = open(os.path.join(H, f), encoding="utf-8").read()
        if "flagmode" in s or (f == "nightlogic.py" and 'startswith("NLIVE")' in s):
            print("already applied: " + f); continue
        for old, new in eds:
            if s.count(old) != 1:
                raise SystemExit("ANCHOR PROBLEM in %s (%d matches): %r - nothing written" % (f, s.count(old), old[:70]))
            s = s.replace(old, new)
        texts[f] = s
    for f, s in texts.items():
        shutil.copy(os.path.join(H, f), os.path.join(H, f + ".bak1118l"))
        open(os.path.join(H, f), "w", encoding="utf-8").write(s)
    print("LIVE FLAG PATCH DONE (%d files)" % len(texts))
if __name__ == "__main__":
    main()
