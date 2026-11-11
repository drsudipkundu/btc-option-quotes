#!/usr/bin/env python3
"""nightwatch - READ-ONLY watchman for the night-sell account (serverbot), 10-Nov-2026.
Sends GET requests only. It never places, changes or cancels an order. AUTO_EXIT is OFF (alerts only).

Why: Sudip rarely reads email, so alerts go to Telegram (state/telegram.env: TG_TOKEN, TG_CHAT, written by him). Email is only
the daily record. Delta has not confirmed option margin / liquidation rules (ticket #484314), so the watchman judges from the
account's own numbers read straight from Delta.

Run by cron every minute:   venv/bin/python nightwatch.py
  --show     print the reading and the level, send nothing, write nothing
  --daily    send the last night result to Telegram (cron 17:36 IST)
  --alive    send one Telegram status line (cron 17:40 and 23:40 IST) so silence means the watchman is down
  --test     send a Telegram test message

Levels (Sudip accepted 10-Nov, scale with account equity; only while an option position is open):
  AMBER    open loss >= backtest worst (USD 93 per 0.01 base) or >= 6 % of equity           -> one alert
  RED      open loss >= 1.5 x that or >= 10 % of equity, or free balance <= 35 % of equity,
           or BTC moved >= 3 % in 15 min against a short                                    -> alert every 2 min until "ack"
  CRITICAL open loss >= 15 % of equity or free balance <= 25 % or liquidation within 1.5 % of price,
           and a short is NOT covered by a long option of the same type                     -> alert every 2 min until "ack"
Reply "ack" to the bot to silence repeats for 30 minutes. Server time is IST."""
import os, sys, csv, json, time, urllib.request, urllib.parse, datetime as dt

H = os.path.expanduser("~/deltabot")
sys.path.insert(0, H)
os.chdir(H)

ACCT = os.environ.get("NW_ACCT", "serverbot")
AUTO_EXIT = False                      # alerts only; the auto buy-back is added later, only after Sudip confirms
CPB = 1000.0                           # contracts per BTC
WORST_USD_PER_001 = 93.0               # backtest worst open loss per 0.01 base (~Rs 7.9k at Rs 85/$)
FX = 88.0                              # rupees per dollar, for display only
AMBER_PCT, RED_PCT, CRIT_PCT = 0.06, 0.10, 0.15
RED_FREE, CRIT_FREE, CRIT_LIQ = 0.35, 0.25, 0.015
MOVE_PCT, MOVE_MIN = 0.03, 15
REPEAT_S, ACK_S = 120, 1800
ENV = os.path.join(H, "state", "telegram.env")
STF = os.path.join(H, "state", "nightwatch_state.json")
HC_F = os.path.join(H, "state", "hc_url")        # optional: Healthchecks.io ping URL (dead-man switch outside the server)
CSV = os.path.join(H, "logs", "nightwatch.csv")
COLS = ["time_ist", "spot", "equity", "available", "free_pct", "open_loss", "open_loss_pct", "short_btc", "long_btc",
        "uncovered_btc", "liq_dist_pct", "move15_pct", "level"]
RANK = {"OK": 0, "AMBER": 1, "RED": 2, "CRITICAL": 3}


def f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def tg_cfg():
    c = {}
    try:
        for ln in open(ENV):
            if "=" in ln:
                k, v = ln.strip().split("=", 1)
                c[k] = v
    except OSError:
        pass
    return c.get("TG_TOKEN"), c.get("TG_CHAT")


def tg_send(text):
    tok, chat = tg_cfg()
    if not tok or not chat:
        print("telegram not configured")
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, data, timeout=15).read()
        return True
    except Exception as e:
        print("telegram send failed:", type(e).__name__)  # never print the URL (it holds the token)
        return False


def tg_commands(st):
    """Texts Sudip sent to the bot since the last check (only from his own chat). Returns a list of lower-case strings."""
    tok, chat = tg_cfg()
    if not tok:
        return []
    try:
        u = "https://api.telegram.org/bot%s/getUpdates?offset=%d&timeout=0" % (tok, int(st.get("tg_offset", 0)))
        res = json.load(urllib.request.urlopen(u, timeout=15)).get("result", [])
    except Exception:
        return []
    out = []
    for r in res:
        st["tg_offset"] = r["update_id"] + 1
        m = r.get("message") or {}
        if str((m.get("chat") or {}).get("id")) == str(chat) and m.get("text"):
            out.append(str(m["text"]).strip().lower().split("@")[0])
    return out


def night_state():
    try:
        return json.load(open(os.path.join(H, "state", "night_nlive.json")))
    except Exception:
        return {}


def result_text():
    ns = night_state()
    ln = ns.get("last_night") or {}
    return "Night sell result: last night %s P&L %.2f USD | running total %.2f USD over %s nights (fees included)." % (
        ln.get("night", "?"), f(ln.get("pnl")), f(ns.get("total_pnl")), ns.get("nights", "?"))


def ctl_state():
    try:
        import control
        return control.get("nlive")["state"]
    except Exception:
        return "unknown"


HELP = ("Commands: /status = night account now | /result = last night and total | /pause = no new night sales | "
        "/resume = allow sales again | ack = pause repeated alerts 30 min | /help")


def handle(cmds, st, now, line, why, pos):
    for c in cmds:
        if c in ("ack", "/ack"):
            st["ack_until"] = now + ACK_S
            tg_send("OK, repeats paused for 30 minutes.")
        elif c == "/status":
            ps = ["%s %s lots @ %s mark %s" % (p.get("product_symbol"), p.get("size"), p.get("entry_price"), p.get("mark_price"))
                  for p in pos if f(p.get("size"))]
            tg_send("STATUS\n%s\n%s\nSales are: %s (base %s)\n%s" % (line, "; ".join(why) or "no warnings",
                    ctl_state(), (json.load(open(os.path.join(H, "state", "night_live_cfg.json"))).get("base") if os.path.exists(os.path.join(H, "state", "night_live_cfg.json")) else "?"),
                    "Positions: " + (" | ".join(ps) if ps else "none")))
        elif c == "/result":
            tg_send(result_text())
        elif c == "/pause":
            try:
                import control
                control.set_state("nlive", "paused")
                tg_send("PAUSED: no new night sales. An open position keeps its resting buy-back. Send /resume to allow sales again.")
            except Exception as e:
                tg_send("Could not pause (%s). Use the Pause button on the control page." % type(e).__name__)
        elif c == "/resume":
            try:
                import control
                control.set_state("nlive", "running")
                tg_send("RESUMED: night sales allowed again.")
            except Exception as e:
                tg_send("Could not resume (%s)." % type(e).__name__)
        elif c in ("/help", "/start"):
            tg_send(HELP)


def hc_ping(suffix=""):
    """Tell the outside dead-man switch (Healthchecks.io) that the watchman is alive. Silent if not configured."""
    try:
        u = open(HC_F).read().strip()
        if u.startswith("https://hc-ping.com/") or u.startswith("https://healthchecks.io/"):
            urllib.request.urlopen(u.rstrip("/") + suffix, timeout=10).read()
    except Exception:
        pass


def read_account():
    from liveorders import Live, Pub
    lv, pub = Live(ACCT), Pub()
    pos = lv._p("GET", "/v2/positions/margined")["result"] or []
    bal = lv._p("GET", "/v2/wallet/balances")["result"] or []
    tk = pub._http("GET", "/v2/tickers/BTCUSD")["result"]
    spot = f(tk.get("spot_price")) or f(tk.get("mark_price"))
    rows = [b for b in bal if f(b.get("balance")) > 0]
    b0 = rows[0] if rows else {}
    return pos, b0, spot


def analyse(pos, b0, spot, st, now):
    wallet, avail = f(b0.get("balance")), f(b0.get("available_balance"))
    short = {"C": 0.0, "P": 0.0}
    long_ = {"C": 0.0, "P": 0.0}
    loss, liq_d = 0.0, None
    for p in pos:
        sym = str(p.get("product_symbol", ""))
        sz = f(p.get("size"))
        if not sz or sym[:2] not in ("C-", "P-"):
            continue
        t = sym[0]
        btc = abs(sz) / CPB
        (short if sz < 0 else long_)[t] += btc
        loss += -sz / CPB * (f(p.get("mark_price")) - f(p.get("entry_price")))   # >0 = losing
        lq = f(p.get("liquidation_price"))
        if lq > 0 and spot > 0 and sz < 0:
            d = abs(lq - spot) / spot
            liq_d = d if liq_d is None else min(liq_d, d)
    equity = wallet   # account money before open P&L; percentages are measured against it
    sh, lg = sum(short.values()), sum(long_.values())
    uncovered = sum(max(0.0, short[t] - long_[t]) for t in "CP")
    # price move over the last 15 minutes
    hist = [h for h in st.get("hist", []) if now - h[0] <= MOVE_MIN * 60 + 90] + [[now, spot]]
    st["hist"] = hist
    old = hist[0][1] if hist else spot
    move = (spot - old) / old if old else 0.0
    base = 0.04
    try:
        base = f(json.load(open(os.path.join(H, "state", "night_live_cfg.json"))).get("base"), 0.04)
    except Exception:
        pass
    worst = WORST_USD_PER_001 * base / 0.01
    level, why = "OK", []
    if sh > 0:
        lp = loss / equity if equity > 0 else 1.0
        free = avail / equity if equity > 0 else 0.0
        if loss >= worst or lp >= AMBER_PCT:
            level = "AMBER"; why.append("open loss %.0f USD (Rs %s) = %.1f %% of the account" % (loss, format(int(loss * FX), ","), lp * 100))
        short_move = (move >= MOVE_PCT and short["C"] > 0) or (move <= -MOVE_PCT and short["P"] > 0)
        if loss >= 1.5 * worst or lp >= RED_PCT or free <= RED_FREE or short_move:
            level = "RED"
            if free <= RED_FREE: why.append("free balance only %.0f %% of the account" % (free * 100))
            if short_move: why.append("BTC moved %.1f %% in %d min against a short" % (move * 100, MOVE_MIN))
        if (lp >= CRIT_PCT or free <= CRIT_FREE or (liq_d is not None and liq_d <= CRIT_LIQ)) and uncovered > 0.0005:
            level = "CRITICAL"; why.append("short NOT covered by insurance (%.3f BTC)" % uncovered)
            if liq_d is not None and liq_d <= CRIT_LIQ: why.append("liquidation only %.1f %% away" % (liq_d * 100))
    row = dict(time_ist=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), spot=round(spot, 1), equity=round(equity, 2),
               available=round(avail, 2), free_pct=round(avail / equity * 100, 1) if equity > 0 else "",
               open_loss=round(loss, 2), open_loss_pct=round(loss / equity * 100, 2) if equity > 0 else "",
               short_btc=round(sh, 4), long_btc=round(lg, 4), uncovered_btc=round(uncovered, 4),
               liq_dist_pct=round(liq_d * 100, 2) if liq_d is not None else "", move15_pct=round(move * 100, 2), level=level)
    return row, level, why


def main():
    now = time.time()
    st = {}
    try:
        st = json.load(open(STF))
    except Exception:
        pass
    if "--test" in sys.argv:
        print("sent" if tg_send("Night watchman test message. Level checks are READ-ONLY, no orders are placed.") else "not sent")
        return
    try:
        pos, b0, spot = read_account()
    except Exception as e:                       # Delta unreachable / rejecting calls: alert after 3 failed minutes in a row
        st["fails"] = st.get("fails", 0) + 1
        hc_ping("/fail")
        print("read failed (%d): %s" % (st["fails"], type(e).__name__))
        if st["fails"] >= 3 and now - st.get("fail_sent", 0) >= 600 and "--show" not in sys.argv:
            if tg_send("RED ALERT - watchman cannot read the night account from Delta for %d minutes (%s). "
                       "Check Delta (halt? login? API key?) and the open positions by hand." % (st["fails"], type(e).__name__)):
                st["fail_sent"] = now
        if "--show" not in sys.argv:
            json.dump(st, open(STF, "w"))
        return
    if st.get("fails", 0) >= 3 and "--show" not in sys.argv:
        tg_send("Delta reading is back after %d failed minutes." % st["fails"])
    st["fails"] = 0
    hc_ping()
    row, level, why = analyse(pos, b0, spot, st, now)
    line = "%s | BTC %.0f | equity %.0f USD | free %s %% | open loss %.0f USD | short %.3f long %.3f BTC | liq %s %% | %s" % (
        row["time_ist"][11:16], spot, row["equity"], row["free_pct"], row["open_loss"], row["short_btc"], row["long_btc"],
        row["liq_dist_pct"] or "n/a", level)
    if "--show" in sys.argv:
        print(line)
        if why:
            print("; ".join(why))
        return
    if "--daily" in sys.argv:
        tg_send(result_text() + " Night account now: " + line)
        return
    if "--alive" in sys.argv:
        tg_send("Night watchman alive. " + line)
        return
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    new = not os.path.exists(CSV)
    # log every 5 min normally, every minute while an option short is open
    if row["short_btc"] > 0 or int(now // 60) % 5 == 0:
        with open(CSV, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            if new:
                w.writeheader()
            w.writerow(row)
    handle(tg_commands(st), st, now, line, why, pos)
    prev = st.get("level", "OK")
    send = False
    if RANK[level] > RANK[prev]:
        send = True                                       # first time at a higher level
    elif RANK[level] >= 2 and now - st.get("last_sent", 0) >= REPEAT_S and now > st.get("ack_until", 0):
        send = True                                       # RED / CRITICAL repeat until ack
    elif level == "OK" and RANK[prev] >= 1:
        tg_send("Night watchman: back to OK. " + line)
    if send:
        icon = {"AMBER": "AMBER", "RED": "RED ALERT", "CRITICAL": "CRITICAL"}[level]
        msg = "%s - night account\n%s\n%s\nAuto buy-back is %s. Reply ack to pause repeats 30 min." % (
            icon, line, "; ".join(why), "ON" if AUTO_EXIT else "OFF (you decide)")
        if tg_send(msg):
            st["last_sent"] = now
    st["level"] = level
    json.dump(st, open(STF, "w"))


if __name__ == "__main__":
    main()
