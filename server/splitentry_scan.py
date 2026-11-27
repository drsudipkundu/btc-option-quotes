#!/usr/bin/env python3
"""splitentry_scan (27-Nov-2026, Sudip 15:58: does a back-test give any edge to "split the entry in time" and "skip or halve the second half after an adverse move"?).
Analysis only; touches no bot, no account. Same data and model as hedgedadd_scan (Binance BTCUSDT 30m, Black-Scholes, everything hedged 4 % beyond, 5 % slippage,
hedges at vol x 1.2, settled at expiry 17:30 IST, the 10 % buy-back NOT modelled).
FULL   : 1.0 of each side (call and put 2.5 % away) sold at 23:30 IST.
SPLIT  : 0.5 at 23:30 and 0.5 at the second time (strikes 2.5 % from the price THEN, own hedge 4 % beyond).
SKIP   : like SPLIT, but the second half of a side is NOT sold when BTC has moved D % against that side by the second time.
HALVE  : like SPLIT, but that second half is 0.25 instead of 0.5.
ONLY-LATE: everything sold at the second time (for reference).
Second sale priced at 50 % vol; "65" columns price the second sale of a side that has moved against at 65 % vol.
Figures: % of the 23:30 spot per 1.0 of full size; night = call + put together."""
import sys, math, datetime as dt
sys.argv = sys.argv[:2]
import entry_time_scan as E

M, DIST, WING, VOL, SLIP, SKEW = 36, 0.025, 0.04, 0.50, 0.05, 1.2
T = lambda n: n * 0.5 / 8760.0
sell = lambda S, K, n, v, c: E.bs(S, K, T(n), v, c) * (1 - SLIP)
buy = lambda S, K, n, v, c: E.bs(S, K, T(n), v * SKEW, c) * (1 + SLIP)
pay = lambda c_, K, call: max(c_ - K, 0) if call else max(K - c_, 0)


def leg(S, n, v, call, c):
    """hedged sale at price S with n half-hours left: P&L in price units per 1 BTC"""
    K = S * (1 + DIST) if call else S * (1 - DIST); Kh = K * (1 + WING) if call else K * (1 - WING)
    return sell(S, K, n, v, call) - buy(S, Kh, n, v, call) - pay(c, K, call) + pay(c, Kh, call)


def main():
    bars = E.fetch(); by = {b[0]: b for b in bars}
    first = ((bars[0][0] + 86400000) // 86400000) * 86400000 + 12 * 3600000
    nights = []
    e = first
    while e < bars[-1][0]:
        e0 = e - M * E.H30; seq = [by.get(e0 + i * E.H30) for i in range(M)]
        if all(seq):
            nights.append(dict(yr=dt.datetime.utcfromtimestamp(e / 1000).year, x=seq[0][1], c=seq[-1][4], cl=[b[4] for b in seq]))
        e += 86400000
    print("nights %d | all hedged 4%% beyond, vol 50%%, slippage 5%%" % len(nights))

    def run(j, mode, D, v_adv):
        """j = half-hours after 23:30 for the second sale. returns per-night P&L list (% of x)"""
        out = []
        for nt in nights:
            x, c = nt["x"], nt["c"]; s = nt["cl"][j - 1]; tot = 0.0
            for call in (True, False):
                adv = ((s / x - 1) if call else (1 - s / x)) * 100
                moved = adv >= D
                first_q = 0.0 if mode == "late" else (1.0 if mode == "full" else 0.5)
                if mode == "full":
                    q2 = 0.0
                elif mode == "late":
                    q2 = 1.0
                elif mode == "split":
                    q2 = 0.5
                elif mode == "skip":
                    q2 = 0.0 if moved else 0.5
                else:
                    q2 = 0.25 if moved else 0.5
                p = first_q * leg(x, M, VOL, call, c)
                if q2:
                    p += q2 * leg(s, M - j, v_adv if moved else VOL, call, c)
                tot += p / x * 100
            out.append(tot)
        return out

    def stats(r):
        n = len(r); m = sum(r) / n; sd = math.sqrt(sum((a - m) ** 2 for a in r) / n)
        srt = sorted(r); w5 = sum(srt[:max(1, n // 20)]) / max(1, n // 20)
        cum = peak = dd = 0.0
        for a in r:
            cum += a; peak = max(peak, cum); dd = max(dd, peak - cum)
        return sum(r), min(r), w5, sd, dd, sum(1 for a in r if a < 0) * 100.0 / n

    def line(name, r, base=None):
        if not r:
            return
        t, w, w5, sd, dd, lose = stats(r)
        print("%-21s %+7.1f %6.2f %6.2f %.3f %6.1f %4.1f" % (name, t, w, w5, sd, dd, lose))

    print("%-21s %7s %6s %6s %5s %6s %4s" % ("", "total", "worst", "wrst5%", "sd", "maxDD", "lose"))
    full = run(6, "full", 1.0, VOL); fs = stats(full)
    line("FULL 23:30", full)
    yrs = sorted(set(nt["yr"] for nt in nights))
    keep = {"FULL": full}
    for j, lab in ((2, "00:30"), (6, "02:30")):
        print("--- second sale at %s IST" % lab)
        line("ONLY-LATE", run(j, "late", 1.0, VOL), fs)
        r = run(j, "split", 9.9, VOL); line("SPLIT 50/50", r, fs); keep["SPLIT " + lab] = r
        r = run(j, "split", 1.0, 0.65); line("SPLIT, 65 after 1.0%", r, fs)
        for D in (0.5, 1.0, 1.5):
            r = run(j, "skip", D, VOL); line("SKIP after %.1f%%" % D, r, fs); keep["SKIP%.1f %s" % (D, lab)] = r
            r = run(j, "halve", D, VOL); line("HALVE after %.1f%%" % D, r, fs)
    print("--- BY YEAR (total)")
    print("%-14s" % "" + " ".join("%6d" % y for y in yrs))
    for k in ("FULL", "SPLIT 02:30", "SKIP1.0 02:30", "SKIP0.5 02:30", "SPLIT 00:30", "SKIP1.0 00:30"):
        r = keep[k]
        print("%-14s" % k + " ".join("%+6.1f" % sum(a for a, nt in zip(r, nights) if nt["yr"] == y) for y in yrs))
    print("--- SINCE 2024 only")
    idx = [i for i, nt in enumerate(nights) if nt["yr"] >= 2024]
    for k in ("FULL", "SPLIT 02:30", "SKIP1.0 02:30", "SKIP0.5 02:30", "SPLIT 00:30", "SKIP1.0 00:30"):
        line(k, [keep[k][i] for i in idx])


if __name__ == "__main__":
    main()
