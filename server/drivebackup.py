#!/usr/bin/env python3
"""Daily shadow-fleet data backup (1-Nov-2026). The server has no Google Drive access, so it e-mails one
tar.gz (base64 text in the mail body) to Sudip's own Gmail; a Claude scheduled task copies it to Drive
folder delta_bot/shadow_backup. Contents: night fleets v4 + v5 (nights CSVs, per-copy trade logs, state) and the
ladder fleets v9-v12 (days CSV, trade logs, state, summary). Read-only on bot files; sends nothing else.
Run by cron at 18:05 IST. Test: python drivebackup.py --dry (prints size, sends nothing)."""
import os, sys, io, tarfile, base64, datetime as dt
HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
ITEMS = ["logs/shadow_nights.csv", "logs/shadow_nights_v5.csv", "logs/shadow", "state/shadow",
         "logs/ladshadow_days.csv", "logs/ladshadow", "state/ladshadow", "state/ladshadow_summary.json"]

def build():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9) as t:
        for it in ITEMS:
            p = os.path.join(HOME, it)
            if os.path.exists(p):
                t.add(p, arcname=it)
    return buf.getvalue()

def main():
    day = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime("%Y%m%d")
    raw = build()
    b64 = base64.b64encode(raw).decode()
    body = ("Shadow fleet backup %s (%d bytes tar.gz). For the Claude Drive copy task - do not delete before it runs.\n"
            "=====B64 START shadow_backup_%s.tar.gz=====\n%s\n=====B64 END=====\n" %
            (day, len(raw), day, "\n".join(b64[i:i + 76] for i in range(0, len(b64), 76))))
    if "--dry" in sys.argv:
        print("dry run: %d bytes tar.gz, mail body %d chars" % (len(raw), len(body)))
        return
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HOME, ".env"))
    import bot as B
    B.Notifier().send("DRIVEBACKUP shadow %s" % day, body)
    print("sent", day, len(raw), "bytes")

if __name__ == "__main__":
    main()
