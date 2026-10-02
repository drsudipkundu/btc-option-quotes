r"""
merge_month.py -- turn every FINISHED month's small CSV files into one Parquet file, then delete the CSVs.

    data/YYYY/MM/DD/quotes_*.csv.gz   ->  parquet/YYYY-MM.parquet
    data/YYYY/MM/DD/missing.csv       ->  parquet/YYYY-MM_missing.csv

Safety: the Parquet is written to a temp name, read back, and its row count must equal the sum of the
CSV rows (plus any rows already in an earlier Parquet for that month) before anything is deleted.
The current month is never touched. Run by .github/workflows/monthly.yml on the 2nd of each month.
"""
import glob
import os
import shutil
import sys
from datetime import datetime, timezone

import pandas as pd


def merge(month_dir, year, month):
    tag = f"{year}-{month}"
    files = sorted(glob.glob(os.path.join(month_dir, "*", "quotes_*.csv.gz")))
    frames = [pd.read_csv(f, dtype={"expiry_tags": "string", "tag": "string"}) for f in files]
    target = os.path.join("parquet", f"{tag}.parquet")
    if os.path.exists(target):                                     # late files for an already-merged month
        frames.insert(0, pd.read_parquet(target))
    if not frames:
        return f"{tag}: no snapshot files"
    df = pd.concat(frames, ignore_index=True)
    for c in ("ts_utc", "fetch_utc", "api_ts_utc", "expiry_utc"):
        df[c] = pd.to_datetime(df[c], utc=True, format="ISO8601")
    df = df.sort_values(["ts_utc", "symbol"], kind="stable").reset_index(drop=True)
    expected = len(df)

    os.makedirs("parquet", exist_ok=True)
    tmp = target + ".tmp"
    df.to_parquet(tmp, index=False, compression="zstd")
    if len(pd.read_parquet(tmp)) != expected:
        os.remove(tmp)
        raise RuntimeError(f"{tag}: row count check failed -- nothing deleted")
    os.replace(tmp, target)

    miss = sorted(glob.glob(os.path.join(month_dir, "*", "missing.csv")))
    mtarget = os.path.join("parquet", f"{tag}_missing.csv")
    if miss:
        parts = ([pd.read_csv(mtarget)] if os.path.exists(mtarget) else []) + [pd.read_csv(m) for m in miss]
        pd.concat(parts, ignore_index=True).to_csv(mtarget, index=False)

    shutil.rmtree(month_dir)
    return f"{tag}: {len(files)} snapshot files, {expected:,} rows -> {target} ({os.path.getsize(target)/1e6:.1f} MB)"


def main():
    now = datetime.now(timezone.utc)
    current = (now.year, now.month)
    done = 0
    for month_dir in sorted(glob.glob(os.path.join("data", "[0-9]" * 4, "[0-9]" * 2))):
        year, month = month_dir.split(os.sep)[-2:]
        if (int(year), int(month)) >= current:
            continue
        print(merge(month_dir, year, month))
        done += 1
    if not done:
        print("no finished month to merge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
