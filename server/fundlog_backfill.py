# 3-Nov-2026: merge the collector's funding-rate history (every 30 min since 2-Oct) into logs/funding_rate.csv, then refresh the summary.
import os, sys, csv
H = os.path.expanduser("~/deltabot"); sys.path.insert(0, H)
src, dst = sys.argv[1], os.path.join(H, "logs", "funding_rate.csv")
rows = {}
for p in (src, dst):
    if os.path.exists(p):
        for r in csv.DictReader(open(p)):
            rows[r["utc"]] = r
R = sorted(rows.values(), key=lambda r: r["utc"])
with open(dst + ".tmp", "w", newline="") as f:
    w = csv.DictWriter(f, ["utc", "mark", "funding_rate_pct_8h"]); w.writeheader(); w.writerows(R)
os.replace(dst + ".tmp", dst)
import fundlog; S = fundlog.summarize()
print(len(R), "rate rows; 30d mean %/8h:", S["rate"].get("30d", {}).get("mean_pct_8h"), "time negative:", S["rate"].get("30d", {}).get("share_negative"))
