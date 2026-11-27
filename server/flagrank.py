#!/usr/bin/env python3
"""flagrank (27-Nov-2026 c33, Sudip: "build that tracker"): PAPER LOG ONLY for two size-rule ideas from the 27-Nov flag study.
Reads what the night seller already wrote (state/prem_hist.csv, state/iv_hist.csv, state/night_nlive.json) and writes one line
per night to logs/flagrank.csv. Never places an order, never calls the exchange, never changes a setting or a state file.

For each night: premium rank and volatility rank against the previous 365 days, the flags, the trend-leg multiplier live used,
and what it would have been under
  rule 1: premium rank above 95 %            -> no extra size (x1.0)
  rule 2: no flag, volatility rank 70-80 %   -> x1.0 instead of x0.5
Run:  flagrank.py          add missing nights      flagrank.py report      show the log"""
import csv, datetime as dt, json, os, sys

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
OUT = os.path.join(HOME, "logs", "flagrank.csv")
MIN_N, P_LINE, V_LINE, TOP, MID_LO, MID_HI = 60, 0.90, 0.80, 0.95, 0.70, 0.80
FLAG_MULT, NOFLAG_MULT = 1.5, 0.5
COLS = ["night", "prem_pct", "prem_rank", "prem_n", "iv", "iv_rank", "iv_n", "P", "V", "R", "flags_from",
        "live_mult", "rule1_mult", "rule2_mult", "rule12_mult", "changed", "logged_at"]


def read_hist(path):
    """{night: value} from a one-value-per-night file (first value of a night wins, as the bot writes it once)."""
    d = {}
    try:
        for r in csv.reader(open(path)):
            if len(r) >= 2 and r[0][:2] == "20" and r[0] not in d:
                try:
                    d[r[0]] = float(r[1])
                except ValueError:
                    pass
    except OSError:
        pass
    return d


def rank(hist, night):
    """(share of the previous 365 days' values at or below this night's value, nights used); (None, n) if too few."""
    if night not in hist:
        return None, 0
    lo = (dt.datetime.strptime(night, "%Y-%m-%d") - dt.timedelta(days=365)).strftime("%Y-%m-%d")
    past = [v for d, v in hist.items() if lo <= d < night]
    if len(past) < MIN_N:
        return None, len(past)
    return sum(1 for v in past if v <= hist[night]) / float(len(past)), len(past)


def live_flags(home):
    """{night: flags dict} the live seller saved for its latest night (may be empty)."""
    out = {}
    try:
        S = json.load(open(os.path.join(home, "state", "night_nlive.json")))
    except Exception:
        return out
    cands = [S] + [v for v in S.values() if isinstance(v, dict)] if isinstance(S, dict) else []
    for c in cands:
        f = c.get("flags_night") if isinstance(c, dict) else None
        if isinstance(f, dict) and f.get("night"):
            out[str(f["night"])] = f
    return out


def decide(pr, vr, P, V, R, live_mult=None):
    """multipliers on the trend leg: (live, rule 1, rule 2, both)."""
    flag = bool(P or V or R)
    live = live_mult if live_mult is not None else (FLAG_MULT if flag else NOFLAG_MULT)
    top = pr is not None and pr > TOP
    mid = (not flag) and vr is not None and MID_LO <= vr < MID_HI
    r1 = 1.0 if (top and live > 1.0) else live
    r2 = 1.0 if (mid and live < 1.0) else live
    r12 = r1 if r1 != live else r2
    return live, r1, r2, r12


def build(home=HOME, now=None):
    prem = read_hist(os.path.join(home, "state", "prem_hist.csv"))
    iv = read_hist(os.path.join(home, "state", "iv_hist.csv"))
    lf = live_flags(home)
    stamp = (now or dt.datetime.now()).strftime("%Y-%m-%d %H:%M")
    rows = []
    for night in sorted(set(prem) | set(iv)):
        pr, pn = rank(prem, night)
        vr, vn = rank(iv, night)
        if pr is None and vr is None:
            continue
        f = lf.get(night)
        if f:
            P, V, R, src, lm = bool(f.get("P")), bool(f.get("V")), bool(f.get("R")), "live", f.get("mult")
            lm = float(lm) if lm is not None else None
        else:                                   # older night: RSI flag not stored, so only P and V are known
            P, V, R, src, lm = (pr is not None and pr >= P_LINE), (vr is not None and vr >= V_LINE), "", "rank-only", None
        live, r1, r2, r12 = decide(pr, vr, P, V, R if R != "" else False, lm)
        rows.append(dict(night=night, prem_pct=prem.get(night, ""), prem_rank="" if pr is None else round(pr, 3), prem_n=pn,
                         iv=iv.get(night, ""), iv_rank="" if vr is None else round(vr, 3), iv_n=vn,
                         P=int(P), V=int(V), R=("" if R == "" else int(R)), flags_from=src,
                         live_mult=live, rule1_mult=r1, rule2_mult=r2, rule12_mult=r12,
                         changed=int(r12 != live), logged_at=stamp))
    return rows


def main(home=HOME, now=None):
    out = os.path.join(home, "logs", "flagrank.csv")
    have = {}
    try:
        for r in csv.DictReader(open(out)):
            have[r["night"]] = r
    except OSError:
        pass
    added = 0
    for r in build(home, now):
        old = have.get(r["night"])
        if old is None or (old.get("flags_from") != "live" and r["flags_from"] == "live"):
            have[r["night"]] = r
            added += 1
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for n in sorted(have):
            w.writerow(have[n])
    os.replace(tmp, out)
    print("flagrank: %d nights in the log, %d added or updated" % (len(have), added))
    return added


def report(home=HOME):
    out = os.path.join(home, "logs", "flagrank.csv")
    try:
        rows = list(csv.DictReader(open(out)))
    except OSError:
        print("no log yet")
        return
    live = [r for r in rows if r["flags_from"] == "live"]
    print("nights logged %d (with live flags %d); rule 1 would change %d, rule 2 would change %d" % (
        len(rows), len(live), sum(1 for r in rows if r["rule1_mult"] != r["live_mult"]), sum(1 for r in rows if r["rule2_mult"] != r["live_mult"])))
    print("night       prem_rank iv_rank  P V R  live  rule1 rule2  source")
    for r in rows[-12:]:
        print("%s  %8s %8s  %s %s %s  %4s  %4s  %4s   %s" % (r["night"], r["prem_rank"] or "-", r["iv_rank"] or "-", r["P"], r["V"], r["R"] or "-",
                                                           r["live_mult"], r["rule1_mult"], r["rule2_mult"], r["flags_from"]))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        report()
    else:
        main()
