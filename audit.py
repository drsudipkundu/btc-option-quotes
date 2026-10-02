r"""
audit.py -- find half-hour slots of a finished UTC day that have NO snapshot at all, and list them in
that day's missing.csv. (GitHub sometimes starts scheduled runs late or skips them under load; a failed
collector already records itself, but a run that never started cannot -- this catches those.)

A slot HH:00 / HH:30 counts as covered if ANY snapshot (half-hourly or evening) exists between the slot
and 29 minutes after it, because GitHub's start delay is normal and the real time is in every row.
Runs inside the evening workflow for yesterday; re-running is harmless (already-listed slots are skipped).

    python audit.py _out 2026-10-01      # writes rows to _out/data/2026/10/01/missing.csv
"""
import csv
import os
import re
import sys
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
NAME_RE = re.compile(r"^quotes_(\d{2})(\d{2})_[a-z]+\.csv\.gz$")
FIRST_DAY = "2026-10-03"         # first FULL day of the archive (2-Oct started mid-day); earlier days are not audited
REASON = "no snapshot in this half-hour (scheduled run skipped or very late)"


def main():
    out, day = sys.argv[1], datetime.strptime(sys.argv[2], "%Y-%m-%d").replace(tzinfo=UTC)
    if sys.argv[2] < FIRST_DAY:
        print(f"audit {sys.argv[2]}: before the archive started, skipped")
        return 0
    rel = os.path.join("data", f"{day:%Y}", f"{day:%m}", f"{day:%d}")
    have = set()
    if os.path.isdir(rel):
        for f in os.listdir(rel):
            m = NAME_RE.match(f)
            if m:
                have.add(int(m.group(1)) * 60 + int(m.group(2)))
    already = set()
    mpath = os.path.join(rel, "missing.csv")
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            already = {r["slot_utc"] for r in csv.DictReader(f) if r["reason"] == REASON}

    gaps = []
    for k in range(48):
        start = k * 30
        if not any(start <= t < start + 30 for t in have):
            slot = day + timedelta(minutes=start)
            if slot.isoformat() not in already:
                gaps.append(slot)
    if not gaps:
        print(f"audit {day:%Y-%m-%d}: all 48 half-hour slots covered")
        return 0

    od = os.path.join(out, rel)
    os.makedirs(od, exist_ok=True)
    opath = os.path.join(od, "missing.csv")
    new = not os.path.exists(opath)
    with open(opath, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(["slot_utc", "slot_ist", "tag", "reason", "logged_utc"])
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        for s in gaps:
            w.writerow([s.isoformat(), s.astimezone(IST).isoformat(), "halfhour", REASON, now])
    print(f"audit {day:%Y-%m-%d}: {len(gaps)} of 48 half-hour slots had no snapshot -> missing.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
