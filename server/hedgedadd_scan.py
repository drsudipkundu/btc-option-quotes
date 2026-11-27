#!/usr/bin/env python3
"""hedgedadd_scan (27-Nov-2026, Sudip 15:44: "want to test both but all must be hedged; hedge may be the old strike or a new further away strike").
Analysis only; touches no bot, no account.  Same data and model as addqty_scan (Binance BTCUSDT 30m, Black-Scholes), but EVERYTHING is hedged.
Each night: a call and a put sold 2.5 % OTM at 23:30 IST, each with a far option bought 4 % beyond its strike (the live rule). Settled at expiry 17:30 IST.
If BTC moves ADVERSE by D % from the entry spot within H hours (30-minute closes, once per leg), sell q=1 more, with its own hedge:
  A1 same strike, hedge = the OLD hedge strike          A2 same strike, hedge = NEW further strike (4 % beyond a strike 2.5 % from the new price)
  B1 NEW strike 2.5 % from the new price, hedge = OLD hedge strike (narrow gap)     B2 NEW strike, hedge 4 % beyond the new strike
Prices: sold options at vol V (first sale 50 %; the add at 50 % or 65 %), hedges at V x 1.2 (far options cost more than flat vol says),
5 % slippage against us on every sale and every purchase. The 10 % buy-back and the crash guard are NOT modelled.
All figures: % of the entry spot per 1 BTC of option; totals are sums over legs.
Usage: python3 hedgedadd_scan.py [cache.json] [--full]"""
import sys, math, datetime as dt
FULL = "--full" in sys.argv
sys.argv = [a for a in sys.argv if a != "--full"][:2]
import entry_time_scan as E

M, DIST, WING, VOL, SLIP, SKEW = 36, 0.025, 0.04, 0.50, 0.05, 1.2


def T(n):
    return n * 0.5 / 8760.0


def sell(S, K, n, v, call):
    return E.bs(S, K, T(n), v, call) * (1 - SLIP)


def buy(S, K, n, v, call):
    return E.bs(S, K, T(n), v * SKEW, call) * (1 + SLIP)


def pay(c, K, call):
    return max(c - K, 0) if call else max(K - c, 0)


def far(K, call):
    return K * (1 + WING) if call else K * (1 - WING)


def main():
    bars = E.fetch(); by = {b[0]: b for b in bars}
    first = ((bars[0][0] + 86400000) // 86400000) * 86400000 + 12 * 3600000
    legs = []
    e = first
    while e < bars[-1][0]:
        e0 = e - M * E.H30; seq = [by.get(e0 + i * E.H30) for i in range(M)]
        if all(seq):
            x = seq[0][1]; c = seq[-1][4]; yr = dt.datetime.utcfromtimestamp(e / 1000).year
            for call in (True, False):
                K = x * (1 + DIST) if call else x * (1 - DIST); Kh = far(K, call)
                p0 = sell(x, K, M, VOL, call); h0 = buy(x, Kh, M, VOL, call)
                un = (p0 - pay(c, K, call)) / x * 100
                hd = (p0 - pay(c, K, call) - h0 + pay(c, Kh, call)) / x * 100
                legs.append(dict(yr=yr, call=call, x=x, K=K, Kh=Kh, c=c, cl=[b[4] for b in seq], un=un, hd=hd, hc=h0 / p0))
        e += 86400000
    n = len(legs)
    print("nights %d, legs %d | first sale: strike 2.5%% away, hedge 4%% beyond, vol 50%%, hedge priced at vol x1.2, slippage 5%%" % (n // 2, n))
    print("NO ADD  unhedged: total %+.1f  worst leg %.2f   |   hedged (live-like): total %+.1f  worst leg %.2f  | hedge cost = %.0f%% of premium" % (
        sum(l["un"] for l in legs), min(l["un"] for l in legs), sum(l["hd"] for l in legs), min(l["hd"] for l in legs), 100 * sum(l["hc"] for l in legs) / n))

    def run(var, D, H, vadd):
        out = []
        for l in legs:
            d = None
            for j, s in enumerate(l["cl"]):
                if (j + 1) * 0.5 > H or j + 1 >= M:
                    break
                adv = (s / l["x"] - 1) if l["call"] else (1 - s / l["x"])
                if adv >= D:
                    rem = M - (j + 1); call = l["call"]
                    Kn = s * (1 + DIST) if call else s * (1 - DIST)
                    Ka = l["K"] if var[0] == "A" else Kn
                    Kha = l["Kh"] if var[1] == "1" else far(Kn, call)
                    ok = (Kha > Ka) if call else (Kha < Ka)
                    if not ok:
                        break
                    cr = sell(s, Ka, rem, vadd, call) - buy(s, Kha, rem, vadd, call)
                    d = (cr - pay(l["c"], Ka, call) + pay(l["c"], Kha, call)) / l["x"] * 100
                    break
            out.append(d)
        return out

    names = dict(A1="A1 same strike, old hedge ", A2="A2 same strike, new hedge ", B1="B1 new strike,  old hedge ", B2="B2 new strike,  new hedge ")
    print("\nvariant                    D%   H   add-vol | trig%  total chg  avg/trig  add won%  worst add | worst leg: hedged no-add -> with add")
    cfgs = [(D, H, v) for H in ((3, 6, 12) if FULL else (3, 6)) for D in ((0.01, 0.015, 0.02) if FULL else (0.01, 0.015)) for v in (0.50, 0.65)]
    keep = {}
    for var in ("A1", "A2", "B1", "B2"):
        for D, H, v in cfgs:
            r = run(var, D, H, v); tr = [d for d in r if d is not None]
            if not tr:
                continue
            wl = min(l["hd"] + (d or 0.0) for l, d in zip(legs, r))
            print("%s %.1f  %2d   %2d%%    | %5.1f  %+8.1f   %+6.3f    %5.1f    %6.2f   | %6.2f -> %6.2f" % (
                names[var], D * 100, H, v * 100, 100.0 * len(tr) / n, sum(tr), sum(tr) / len(tr), 100.0 * sum(1 for d in tr if d > 0) / len(tr), min(tr),
                min(l["hd"] for l in legs), wl))
            keep[(var, D, H, v)] = r
    print("\nBY YEAR, total change (D 1.5%, H 3 h = until about 02:30, add at 65% vol / at 50% vol)")
    yrs = sorted(set(l["yr"] for l in legs))
    print("variant " + " ".join("%11d" % y for y in yrs))
    for var in ("A1", "A2", "B1", "B2"):
        a, b = keep[(var, 0.015, 3, 0.65)], keep[(var, 0.015, 3, 0.50)]
        print("%-7s " % var + " ".join("%+5.1f/%+5.1f" % (sum(d or 0 for l, d in zip(legs, a) if l["yr"] == y), sum(d or 0 for l, d in zip(legs, b) if l["yr"] == y)) for y in yrs))
    print("hedged no-add by year: " + " ".join("%d %+.1f |" % (y, sum(l["hd"] for l in legs if l["yr"] == y)) for y in yrs))


if __name__ == "__main__":
    main()
