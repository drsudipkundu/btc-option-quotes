"""6-Nov-2026: read-only. From the recorded option books (optbook/*.jsonl[.gz]) at the night entry time (23:25-23:40 IST),
how much could be SOLD into the bids for 2-6 % OTM options, and at what average price vs the best bid.
Sizes tested: 20, 40, 60, 120, 180 contracts (0.02 .. 0.18 BTC)."""
import glob, gzip, json, os, statistics as st, datetime as dt, collections
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
D = os.path.expanduser("~/deltabot/optbook")
SIZES = (20, 40, 60, 120, 180)
res = collections.defaultdict(list); nights = set(); books = 0
for f in sorted(glob.glob(D + "/*_23.jsonl*")):
    op = gzip.open if f.endswith(".gz") else open
    seen = {}
    with op(f, "rt") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            t = dt.datetime.fromtimestamp(r["t"], IST)
            if not (25 <= t.minute <= 40):
                continue
            otm = (r["k"] / r["sp"] - 1) if r["ty"] == "C" else (1 - r["k"] / r["sp"])
            if not (0.02 <= otm <= 0.06) or not r["bids"]:
                continue
            key = (r["s"], t.strftime("%Y%m%d%H%M"))
            if key in seen:
                continue
            seen[key] = 1; books += 1; nights.add(t.date())
            best = r["bids"][0][0]
            for n in SIZES:
                left, got = n, 0.0
                for p, q in r["bids"]:
                    take = min(left, q); got += take * p; left -= take
                    if left <= 0:
                        break
                filled = n - max(left, 0)
                res[n].append((filled / n, (got / filled / best) if filled else 0, best))
print("nights:", len(nights), sorted(nights)[0] if nights else "-", "->", sorted(nights)[-1] if nights else "-", "| books:", books)
for n in SIZES:
    v = res[n]
    if not v:
        continue
    full = [x for x in v if x[0] >= 0.999]
    print("sell %3d contracts (%.2f BTC): fully filled in %3.0f %% of books | when full, avg price = %.0f %% of best bid (median), worst %.0f %%" % (
        n, n / 1000, 100 * len(full) / len(v), 100 * st.median([x[1] for x in full]) if full else 0, 100 * min([x[1] for x in full]) if full else 0))
print("median best bid USD:", round(st.median([x[2] for x in res[SIZES[0]]]), 1) if res[SIZES[0]] else "-")
