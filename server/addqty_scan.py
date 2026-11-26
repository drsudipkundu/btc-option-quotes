#!/usr/bin/env python3
"""addqty_scan - morning point 2 (26-Nov-2026): sell a strike at 23:30 IST; if BTC then moves ADVERSE (up for a call, down for a put) by D % from the
entry spot, sell q more of the SAME strike. Compare with not adding. Analysis only; touches no bot, no account.
Each night gives two legs (call and put, 2.5 % OTM, strikes fixed at entry). P&L per 1 BTC of option, in % of entry spot.
Premium = Black-Scholes (vol 50 %, or higher for the add price), 5 % slippage on every sale. Settled at expiry (17:30 IST); the 10 % buy-back is NOT modelled.
Trigger checked at each 30-minute bar CLOSE after entry, only within the first H hours, once per leg.  Data: Binance BTCUSDT 30m (same cache as entry_time_scan).
Usage: python3 addqty_scan.py [cache.json]"""
import sys, math, datetime as dt
sys.argv = sys.argv[:2] if len(sys.argv) > 1 else sys.argv
import entry_time_scan as E

M = 36                       # 23:30 IST = 18:00 UTC, expiry 12:00 UTC -> 36 half-hours
DIST, VOL, SLIP = 0.025, 0.50, 0.05


def prem(S, K, nbars, v, call):
    return E.bs(S, K, nbars * 0.5 / 8760.0, v, call) * (1 - SLIP)


def main():
    bars = E.fetch(); by = {b[0]: b for b in bars}
    first = ((bars[0][0] + 86400000) // 86400000) * 86400000 + 12 * 3600000
    legs = []          # per leg: year, call?, x, K, c, pnl0, path closes
    e = first
    while e < bars[-1][0]:
        e0 = e - M * E.H30; seq = [by.get(e0 + i * E.H30) for i in range(M)]
        if all(seq):
            x = seq[0][1]; c = seq[-1][4]; yr = dt.datetime.utcfromtimestamp(e / 1000).year
            for call in (True, False):
                K = x * (1 + DIST) if call else x * (1 - DIST)
                pay = max(c - K, 0) if call else max(K - c, 0)
                legs.append((yr, call, x, K, pay, prem(x, K, M, VOL, call), [b[4] for b in seq], e))
        e += 86400000
    print("nights: %d  legs: %d  (strike %.1f%% OTM, vol %d%%, slip %d%%)" % (len(legs) // 2, len(legs), DIST * 100, VOL * 100, SLIP * 100))
    base = [(l[5] - l[4]) / l[2] * 100 for l in legs]
    print("baseline no add: total %.1f  avg/leg %.3f  worst leg %.2f  legs ITM at expiry %d" % (sum(base), sum(base) / len(base), min(base), sum(1 for l in legs if l[4] > 0)))
    print("\n D%%  H(h)  q  vadd |trig%%  avg d/trig  total d  win%%add  worst add  worst leg base->add | rebound(add wins) / hit(add loses)")

    def run(D, H, q, vadd):
        res = []
        for i, (yr, call, x, K, pay, p0, cl, e_) in enumerate(legs):
            b0 = base[i]; d = 0.0; hit = False
            for j, s in enumerate(cl):                       # close of bar j, i.e. (j+1)*0.5 h after entry
                if (j + 1) * 0.5 > H or j + 1 >= M:
                    break
                adv = (s / x - 1) if call else (1 - s / x)
                if adv >= D:
                    pa = prem(s, K, M - (j + 1), vadd, call)
                    d = q * (pa - pay) / x * 100; hit = True; break
            res.append((yr, d, hit, b0))
        return res

    cfgs = [(D, H, q, v) for D in (0.01, 0.015, 0.02) for H in (3, 6, 12, 18) for q in (1, 2) for v in (0.50, 0.65)]
    keep = {}
    for D, H, q, v in cfgs:
        r = run(D, H, q, v); tr = [x for x in r if x[2]]
        if not tr:
            continue
        tot = sum(x[1] for x in r); wins = sum(1 for x in tr if x[1] > 0) / len(tr) * 100
        wb = min(x[3] for x in r); wa = min(x[3] + x[1] for x in r)
        reb = sum(1 for x in tr if x[1] > 0); hit = len(tr) - reb
        print(" %3.1f  %3d  %d  %.2f |%5.1f  %9.3f  %7.1f  %7.1f  %9.2f  %7.2f -> %7.2f | %d / %d" % (D * 100, H, q, v, len(tr) / len(r) * 100, tot / len(tr), tot, wins, min(x[1] for x in tr), wb, wa, reb, hit))
        keep[(D, H, q, v)] = r
    print("\nBY YEAR, total change (sum of d, % pts) for chosen configs: D H q vadd")
    for key in [(0.015, 12, 1, 0.5), (0.02, 12, 1, 0.5), (0.015, 6, 1, 0.65), (0.02, 6, 1, 0.65)]:
        r = keep.get(key)
        if r:
            ys = sorted({x[0] for x in r})
            print(key, "  ".join("%d:%+.1f" % (y, sum(x[1] for x in r if x[0] == y)) for y in ys))
    print("\nlargest move from entry to expiry in data: up %.1f%%  down %.1f%%" % (max((l[6][-1] / l[2] - 1) * 100 for l in legs), max((1 - l[6][-1] / l[2]) * 100 for l in legs)))


if __name__ == "__main__":
    main()
