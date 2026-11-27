#!/usr/bin/env python3
"""cutrank - PAPER ONLY (built 27-Nov-2026, Sudip 14:58 IST: "proceed, all these will stay as paper and collect as much data as required").
Answers: if the night sell had to free X rupees of margin, WHICH legs and how much should be bought back? It compares two plans on the open night position:
  A) FIXED STEPS  = stagedrel.plan_cuts (put top-up, then 50/30/20 % of the small base, calls by decay, alternating)
  B) MATH RANK    = rank every open sold leg by  margin freed per BTC / cost of closing one BTC,  close the best ratio first, stop when enough is freed.
     cost of closing 1 BTC = spread (7 % of mark + 0.2 USD) + fee (0.03 % of spot, max 3.5 % of the price) + forgone edge (edge x mark: what holding to expiry would still earn).
     margin freed per BTC = the fitted formula of stagedrel (0.0048/0.0050 x spot + 1.2375 x mark). The far hedge is never cut.
Scenarios: the need is 25 %, 50 % and 100 % of all margin the open sold legs hold (the ladder needs nothing today, so these are pretend needs).
It only sends GET requests. It NEVER places an order, never moves money, never changes a setting. Log: logs/cutrank.csv (one row per scenario).
  venv/bin/python cutrank.py          run (cron every 30 minutes, only while a night position is open): log, no message
  venv/bin/python cutrank.py --show   run and only print (no log)
Settings in state/cutrank_cfg.json (only the keys you list change). No order code exists in this file."""
import os, sys, csv, json, math, time, datetime as dt

H = os.path.expanduser(os.environ.get("BOT_HOME", "~/deltabot"))
sys.path.insert(0, H)
STATE = os.path.join(H, "state"); LOGS = os.path.join(H, "logs")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
C = 0.001

CFG = dict(spread_frac=0.07, spread_usd=0.2, fee_frac=0.0003, fee_cap_frac=0.035, edge_frac=0.15,
           tie_pct=10.0, scenarios=[0.25, 0.5, 1.0], fx=85.0)


def jl(p):
    try:
        return json.load(open(p))
    except Exception:
        return {}


def load_cfg():
    import stagedrel as SD
    c = dict(SD.load_cfg()); c.update(CFG)
    c.update(jl(os.path.join(STATE, "cutrank_cfg.json")))
    return c


def close_cost(c, spot, mark):
    """USD cost of buying back 1 BTC of an option with this mark: spread + fee + forgone edge"""
    ask = mark * (1 + c["spread_frac"]) + c["spread_usd"]
    fee = min(c["fee_frac"] * spot, c["fee_cap_frac"] * ask)
    return (ask - mark) + fee + c["edge_frac"] * mark


def plan_rank(c, spot, legs, marks, need_usd):
    """B) math rank. Returns dict(steps=[(label, id, sym, side, qty, freed_usd, cost_usd)], freed, cost, short)"""
    import stagedrel as SD
    rows = []
    for l in legs:
        mk = marks.get(l["sym"], 0.0)
        fb = SD.freed_per_btc(c, l["side"], spot, mk)
        cc = close_cost(c, spot, mk)
        rows.append(dict(l=l, fb=fb, cc=cc, ratio=fb / cc if cc > 0 else 0.0))
    rows.sort(key=lambda r: -r["ratio"])
    # ratios within tie_pct of each other: bigger margin per BTC first
    out, i = [], 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1]["ratio"] >= rows[i]["ratio"] * (1 - c["tie_pct"] / 100.0):
            j += 1
        out += sorted(rows[i:j + 1], key=lambda r: -r["fb"]); i = j + 1
    steps, freed, cost = [], 0.0, 0.0
    for r in out:
        if freed >= need_usd - 1e-9:
            break
        l = r["l"]
        q = math.floor(l["qty"] / C + 1e-9) * C
        if r["fb"] <= 0 or q < C - 1e-12:
            continue
        if freed + q * r["fb"] > need_usd:
            q = min(q, math.ceil(max(need_usd - freed, 0) / r["fb"] / C - 1e-9) * C)
        if q < C - 1e-12:
            continue
        steps.append(("rank %.1f" % r["ratio"], l["id"], l["sym"], l["side"], round(q, 3), q * r["fb"], q * r["cc"]))
        freed += q * r["fb"]; cost += q * r["cc"]
    return dict(steps=steps, freed=freed, cost=cost, short=max(need_usd - freed, 0.0))


def plan_fixed(c, spot, legs, marks, need_usd):
    """A) the fixed-step plan of stagedrel, plus its closing cost on the same cost model"""
    import stagedrel as SD
    p = SD.plan_cuts(c, spot, legs, marks, need_usd)
    cost = sum(s[4] * close_cost(c, spot, marks.get(s[2], 0.0)) for s in p["steps"])
    p["cost"] = cost
    return p


def total_margin(c, spot, legs, marks):
    import stagedrel as SD
    return sum(l["qty"] * SD.freed_per_btc(c, l["side"], spot, marks.get(l["sym"], 0.0)) for l in legs)


def scenarios(c, spot, legs, marks):
    tot = total_margin(c, spot, legs, marks)
    res = []
    for sc in c["scenarios"]:
        need = tot * sc
        res.append(dict(sc=sc, need=need, A=plan_fixed(c, spot, legs, marks, need), B=plan_rank(c, spot, legs, marks, need)))
    return tot, res


def txt(p):
    return "; ".join("%s %.3f" % (s[3] + " " + s[2].split("-")[-2] if "-" in s[2] else s[2], s[4]) for s in p["steps"]) or "-"


def main():
    show = "--show" in sys.argv
    c = load_cfg()
    st = jl(os.path.join(STATE, "night_nlive.json"))
    legs = [l for l in (st.get("legs") or []) if l.get("dir") == "S" and not l.get("closed") and l.get("kind") != "ins"]
    if not legs:
        print("no night position open: nothing to rank"); return
    from liveorders import Pub
    pub = Pub()
    tk = pub._http("GET", "/v2/tickers/BTCUSD")["result"]
    spot = float(tk.get("spot_price") or tk.get("mark_price"))
    marks = {}
    for l in legs:
        try:
            marks[l["sym"]] = float(pub._http("GET", "/v2/tickers/%s" % l["sym"])["result"].get("mark_price") or 0)
        except Exception:
            marks[l["sym"]] = 0.0
    tot, res = scenarios(c, spot, legs, marks)
    now = dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    print("CUT RANKING (paper only) %s IST, BTC %.0f, open sold legs hold about %s margin" % (now, spot, "Rs %s" % format(int(round(tot * c["fx"], -2)), ",")))
    for r in res:
        print(" need %d%% = Rs %s | A fixed steps: frees Rs %s, cost Rs %s [%s] | B math rank: frees Rs %s, cost Rs %s [%s]" % (
            round(r["sc"] * 100), format(int(round(r["need"] * c["fx"], -2)), ","),
            format(int(round(r["A"]["freed"] * c["fx"], -2)), ","), format(int(round(r["A"]["cost"] * c["fx"], -1)), ","), txt(r["A"]),
            format(int(round(r["B"]["freed"] * c["fx"], -2)), ","), format(int(round(r["B"]["cost"] * c["fx"], -1)), ","), txt(r["B"])))
    if show:
        return
    os.makedirs(LOGS, exist_ok=True)
    p = os.path.join(LOGS, "cutrank.csv"); new = not os.path.exists(p)
    with open(p, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["time_ist", "night", "spot", "total_margin_usd", "need_pct", "need_usd", "A_freed", "A_cost", "A_short", "A_steps", "B_freed", "B_cost", "B_short", "B_steps"])
        for r in res:
            w.writerow([now, st.get("night"), round(spot, 1), round(tot, 2), round(r["sc"] * 100), round(r["need"], 2),
                        round(r["A"]["freed"], 2), round(r["A"]["cost"], 2), round(r["A"]["short"], 2), txt(r["A"]),
                        round(r["B"]["freed"], 2), round(r["B"]["cost"], 2), round(r["B"]["short"], 2), txt(r["B"])])


if __name__ == "__main__":
    main()
