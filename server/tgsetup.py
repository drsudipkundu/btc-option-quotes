#!/usr/bin/env python3
"""tgsetup - one-time Telegram setup for the night watchman (10-Nov-2026). Run by Sudip in the server terminal.
Asks for the bot token with a hidden prompt, checks it with Telegram, finds his chat, saves state/telegram.env (mode 600)
and sends a test message. The token is never printed. Prints plain reasons if something is wrong."""
import os, sys, json, getpass, urllib.request, urllib.parse, urllib.error

ENV = os.path.expanduser("~/deltabot/state/telegram.env")


def call(tok, method, data=None):
    url = "https://api.telegram.org/bot%s/%s" % (tok, method)
    body = urllib.parse.urlencode(data).encode() if data else None
    try:
        return json.load(urllib.request.urlopen(url, body, timeout=20))
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except Exception:
            return {"ok": False, "description": "HTTP %s" % e.code}
    except Exception as e:
        return {"ok": False, "description": type(e).__name__}


tok = getpass.getpass("Paste the bot token (hidden), then press Enter: ").strip().strip("[]\"' ")
if not tok or ":" not in tok:
    sys.exit("That does not look like a token. It should be digits, a colon, then letters, e.g. 123456789:AAH...  Run again.")
me = call(tok, "getMe")
if not me.get("ok"):
    sys.exit("Telegram rejected this token (%s). Get a fresh one from @BotFather (/mybots > your bot > API Token), then run again." % me.get("description"))
print("Token accepted. Bot name: @%s" % me["result"].get("username"))
up = call(tok, "getUpdates")
chats = {}
for r in up.get("result", []):
    m = r.get("message") or {}
    c = m.get("chat") or {}
    if c.get("id") is not None and c.get("type") == "private":
        chats[c["id"]] = c.get("first_name", "")
if not chats:
    sys.exit("No message from you found. Open @%s in Telegram, press Start, send the word hi, then run this again." % me["result"].get("username"))
cid, name = list(chats.items())[-1]
os.makedirs(os.path.dirname(ENV), exist_ok=True)
with open(ENV, "w") as fh:
    fh.write("TG_TOKEN=%s\nTG_CHAT=%s\n" % (tok, cid))
os.chmod(ENV, 0o600)
r = call(tok, "sendMessage", {"chat_id": cid, "text": "Night watchman connected. Alerts will come here."})
print("SAVED. Test message sent to %s." % (name or "your chat") if r.get("ok") else "Saved, but the test message failed: %s" % r.get("description"))
