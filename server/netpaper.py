#!/usr/bin/env python3
"""netpaper (20-Nov-2026, Sudip 17:20-17:40): PAPER side-by-side test of the night-sell SAFETY NET. Places NO order.
Rule under test (claude/night-damage-control-bad-nights-far-option-or-future-at-loss-trigger-2026-11-20.md):
  only for a side that is NOT covered (sold options > far/insurance options of the same type):
  when that side's open loss reaches TRIG (8 %) of the account -> buy 1x the uncovered quantity of a far option about
  3 % beyond BTC (nearest strike with sellers); if no seller, BTC future with exit 0.5 % back / re-entry at the trigger price.
Smart-buy questions it measures with real Delta books:
  1) WATCH-FIRST vs DECIDE-THEN-LOOK: from ARM (5 %) the far-option books are refreshed every 10 s, so at the trigger the
     strike and price are already known. The time a fresh "look" takes (chain + books) is measured every time = the delay
     the decide-then-look method would add.
  2) ONE ORDER of x vs THREE ORDERS of x/2 on the 3 nearest strikes with sellers (then cancel what is beyond x):
     simulated against the book at the trigger moment -> filled, average price, over-fill and the cost to sell it back.
Afterwards the paper far option (marked each minute) and the paper future are followed to the 17:20 exit, so each night
shows "loss with the net" vs "loss without it".
READ ONLY: GET requests only (account via nightwatch.read_account, books from the public API).
Logs: logs/netpaper_events.csv (one row per decision), logs/netpaper_track.csv (minute marks), state/netpaper_state.json.
Telegram: one PAPER message when it arms and when it would fire.
  venv/bin/python netpaper.py           run forever (systemd service netpaper)
  venv/bin/python netpaper.py --once    one cycle, print, no Telegram"""
import csv, json, os, sys, time, urllib.parse, urllib.request, datetime as dt

H = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
API = "https://api.india.delta.exchange"
ARM, TRIG = 0.05, 0.08              # share of account equity (open loss of the UNCOVERED side)
FAR = 0.03                          # far option distance beyond BTC
FUT_BUF = 0.005                     # future exit 0.5 % back, re-entry at the trigger price
CAP_MULT = 2.0                      # smart-buy price cap = 2 x best ask (same as the crash-guard insurance)
CPB = 1000.0                        # contracts per BTC
STF = os.path.join(H, "state", "netpaper_state.json")
EV = os.path.join(H, "logs", "netpaper_events.csv")
TR = os.path.join(H, "logs", "netpaper_track.csv")
EVC = ["time_ist", "night", "side", "event", "spot", "equity", "side_loss_usd", "side_loss_pct", "uncovered_btc",
       "strike", "best_ask", "look_ms", "one_filled", "one_avg", "split_filled", "split_avg", "split_overfill", "overfill_sellback_usd",
       "fut_book_ok", "note"]
TRC = ["time_ist", "night", "side", "spot", "side_loss_usd", "far_mark", "far_value_usd", "fut_pnl_usd", "fut_pos"]


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "netpaper/1"})
    return json.load(urllib.request.urlopen(req, timeout=10))["result"]


def f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def night_of(now):
    return (now - dt.timedelta(hours=17, minutes=31)).date().isoformat()


def load():
    try:
        return json.load(open(STF))
    except Exception:
        return {}


def save(st):
    json.dump(st, open(STF, "w"), indent=1)


def write(path, cols, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in cols})


def tg(text):
    try:
        sys.path.insert(0, H)
        import nightwatch
        nightwatch.tg_send(text)
    except Exception as e:
        print("telegram failed:", e)


def sides(pos):
    """per type: sold BTC, long BTC, open loss USD (>0 = losing), symbols' expiry"""
    S = {"P": dict(sold=0.0, long=0.0, loss=0.0, exp=None), "C": dict(sold=0.0, long=0.0, loss=0.0, exp=None)}
    for p in pos:
        sym = str(p.get("product_symbol", ""))
        sz = f(p.get("size"))
        if not sz or sym[:2] not in ("C-", "P-"):
            continue
        d = S[sym[0]]
        if sz < 0:
            d["sold"] += -sz / CPB
            d["exp"] = sym.split("-")[-1]
        else:
            d["long"] += sz / CPB
        d["loss"] += -sz / CPB * (f(p.get("mark_price")) - f(p.get("entry_price")))
    return S


def chain(ty, exp):
    """listed options of one type for the expiry code DDMMYY -> [(strike, symbol)]"""
    e = dt.datetime.strptime(exp, "%d%m%y")
    tk = get("/v2/tickers", {"contract_types": "put_options" if ty == "P" else "call_options",
                             "underlying_asset_symbols": "BTC", "expiry_date": e.strftime("%d-%m-%Y")})
    out = []
    for t in tk:
        p = str(t.get("symbol", "")).split("-")
        if len(p) == 4 and p[0] == ty:
            out.append((float(p[2]), t["symbol"]))
    return sorted(out)


def look(ty, exp, spot):
    """the 3 strikes nearest to FAR beyond BTC (going further out), with their books; returns (list, ms taken)"""
    t0 = time.time()
    ch = chain(ty, exp)
    tgt = spot * (1 - FAR) if ty == "P" else spot * (1 + FAR)
    if ty == "P":
        cand = [c for c in sorted(ch, key=lambda c: -c[0]) if c[0] <= tgt][:3] or sorted(ch)[:3]
    else:
        cand = [c for c in sorted(ch) if c[0] >= tgt][:3] or sorted(ch, key=lambda c: -c[0])[:3]
    out = []
    for k, sym in cand:
        try:
            b = get("/v2/l2orderbook/" + sym, {"depth": 20})
        except Exception:
            continue
        asks = [(f(x["price"]), int(x["size"])) for x in (b.get("sell") or [])]
        bids = [(f(x["price"]), int(x["size"])) for x in (b.get("buy") or [])]
        out.append(dict(k=k, sym=sym, asks=asks, bids=bids))
    return out, int((time.time() - t0) * 1000)


def sweep(asks, n, cap):
    got, cost = 0, 0.0
    for px, sz in asks:
        if px > cap or got >= n:
            break
        take = min(sz, n - got)
        got += take
        cost += take * px
    return got, (cost / got if got else 0.0)


def simulate(books, need):
    """one order of `need` contracts on the first strike with sellers vs three orders of need/2 on up to 3 strikes"""
    live = [b for b in books if b["asks"]]
    if not live:
        return None
    b0 = live[0]
    cap0 = b0["asks"][0][0] * CAP_MULT
    one_n, one_avg = sweep(b0["asks"], need, cap0)
    half = max(1, need // 2)
    s_n, s_cost, legs = 0, 0.0, []
    for b in live[:3]:
        n, a = sweep(b["asks"], half, b["asks"][0][0] * CAP_MULT)
        s_n += n
        s_cost += n * a
        legs.append((b, n, a))
    over = max(0, s_n - need)
    sellback, left = 0.0, over                   # extra sold back at the best bids of the last strikes bought
    for b, n, a in reversed(legs):
        if left <= 0:
            break
        x = min(left, n)
        bid = b["bids"][0][0] if b["bids"] else 0.0
        sellback += x * (a - bid) / CPB
        left -= x
    return dict(strike=b0["k"], sym=b0["sym"], ask=b0["asks"][0][0], one_n=one_n, one_avg=one_avg,
                s_n=s_n, s_avg=(s_cost / s_n if s_n else 0.0), over=over, sellback=sellback)


def fut_book_ok(need_btc):
    try:
        b = get("/v2/l2orderbook/BTCUSD", {"depth": 20})
        return sum(int(x["size"]) for x in (b.get("buy") or [])) / CPB >= need_btc
    except Exception:
        return False


def cycle(st, quiet=False):
    sys.path.insert(0, H)
    import nightwatch
    pos, b0, spot = nightwatch.read_account()
    equity = f(b0.get("balance"))
    now = dt.datetime.now()
    night = night_of(now)
    if st.get("night") != night:
        st.clear()
        st["night"] = night
    S = sides(pos)
    armed_any = False
    for ty, nm in (("P", "PUT"), ("C", "CALL")):
        d = S[ty]
        g = st.setdefault(ty, {})
        unc = max(0.0, d["sold"] - d["long"])
        pct = d["loss"] / equity if equity > 0 else 0.0
        base = dict(time_ist=now.strftime("%Y-%m-%d %H:%M:%S"), night=night, side=nm, spot=round(spot, 1), equity=round(equity, 2),
                    side_loss_usd=round(d["loss"], 2), side_loss_pct=round(pct * 100, 2), uncovered_btc=round(unc, 4))
        # follow a fired paper net to the end of the night
        if g.get("fired"):
            fm, fv = 0.0, 0.0
            try:
                tk = get("/v2/tickers/" + g["sym"])
                fm = f(tk.get("mark_price"))
                fv = (fm - g["avg"]) * g["qty"]
            except Exception:
                pass
            sgn = -1.0 if ty == "P" else 1.0
            lv = g["lv"]
            if g["fpos"] == 0 and ((spot <= lv) if ty == "P" else (spot >= lv)):
                g.update(fpos=1, fent=spot)
                g["freal"] -= 0.0005 * spot * g["qty"]
            elif g["fpos"] == 1 and ((spot >= lv * (1 + FUT_BUF)) if ty == "P" else (spot <= lv * (1 - FUT_BUF))):
                g["freal"] += (sgn * (spot - g["fent"]) - 0.0005 * spot) * g["qty"]
                g["fpos"] = 0
            fut = g["freal"] + (sgn * (spot - g["fent"]) * g["qty"] if g["fpos"] else 0.0)
            write(TR, TRC, dict(base, far_mark=fm, far_value_usd=round(fv, 2), fut_pnl_usd=round(fut, 2), fut_pos=g["fpos"]))
            continue
        if unc < 0.0005 or not d["exp"]:
            continue
        if pct >= ARM:
            armed_any = True
            books, ms = look(ty, d["exp"], spot)
            g["books"] = books
            if not g.get("armed"):
                g["armed"] = True
                write(EV, EVC, dict(base, event="ARM", look_ms=ms, note="far-option books now refreshed every 10 s"))
                if not quiet:
                    tg("PAPER safety net ARMED (%s side): uncovered %.3f BTC, open loss %.1f %% of the account. No order is placed."
                       % (nm, unc, pct * 100))
            if pct >= TRIG:
                fresh, ms2 = look(ty, d["exp"], spot)      # what decide-then-look would have to do now
                sim = simulate(fresh or books, int(round(unc * CPB)))
                fok = fut_book_ok(unc)
                row = dict(base, event="WOULD-FIRE", look_ms=ms2, fut_book_ok=int(fok))
                if sim:
                    row.update(strike=sim["strike"], best_ask=sim["ask"], one_filled=sim["one_n"], one_avg=round(sim["one_avg"], 2),
                               split_filled=sim["s_n"], split_avg=round(sim["s_avg"], 2), split_overfill=sim["over"],
                               overfill_sellback_usd=round(sim["sellback"], 2), note="far option")
                    g.update(fired=True, sym=sim["sym"], avg=sim["one_avg"] or sim["ask"], qty=unc)
                else:
                    row.update(note="NO SELLER on far options -> future fallback")
                    g.update(fired=True, sym="", avg=0.0, qty=unc)
                g.update(lv=spot, fpos=1, fent=spot, freal=-0.0005 * spot * unc)
                write(EV, EVC, row)
                if not quiet:
                    tg("PAPER safety net WOULD FIRE now (%s side, loss %.1f %% of account): %s. No order placed - recorded for review."
                       % (nm, pct * 100, ("buy %d contracts of %s at about %.1f (one order filled %d; 3 x half orders filled %d, over-fill %d)"
                                          % (int(round(unc * CPB)), sim["sym"], sim["one_avg"], sim["one_n"], sim["s_n"], sim["over"])) if sim
                          else "no far-option seller, BTC future fallback"))
    return armed_any


def main():
    once = "--once" in sys.argv
    st = load()
    while True:
        armed = False
        try:
            armed = cycle(st, quiet=once)
            save(st)
        except Exception as e:
            print(dt.datetime.now().strftime("%F %T"), "cycle failed:", repr(e), flush=True)
        if once:
            print(json.dumps({k: v for k, v in st.items() if k != "books"}, default=str)[:2000])
            return
        time.sleep(10 if armed else 60)


if __name__ == "__main__":
    main()
