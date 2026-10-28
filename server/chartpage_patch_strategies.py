# Patch for ~/deltabot/chartpage.py (idempotent): adds the v11 / v12 paper-ladder lines to auto() and tags every line with "strat",
# so the chart's strategy dropdown can show one strategy or all. Read-only: only reads state/lv11_state.json and lv12_state.json.
import re, sys
p = sys.argv[1] if len(sys.argv) > 1 else 'chartpage.py'
s = open(p, encoding='utf-8').read()
MARK = '# --- v11 / v12 paper ladders + strategy tags (added 28-Oct-2026'
if MARK in s:
    print('strategy lines already present'); sys.exit(0)
NEW = '''    # --- v11 / v12 paper ladders + strategy tags (added 28-Oct-2026 for the chart strategy dropdown)
    try:
        if sym == "BTCUSD":
            from variants import ERLadder
            sma2 = sma_daily(100)
            for key, kind, nm in (("lv11", "v11", "v11"), ("lv12", "v12m1", "v12")):
                d = (jload(os.path.join(HOME, "state", "%s_state.json" % key), {}) or {}).get("ladder") or {}
                if not (d.get("active") and d.get("lots")):
                    continue
                g = ERLadder(kind)
                g.from_dict(d)
                lots = d["lots"]
                held = 0.0
                for l in lots:
                    held += l["c"] * BTC_PER_C
                    L.append(dict(price=l["buy_price"], label="%s HELD %.3f → sells %.1f" % (nm, l["c"] * BTC_PER_C, g.sell_price(l)), color="#2196f3", dash=True, grp="held", strat=key))
                L.append(dict(price=d["entry"], label="%s ENTRY (cycle %s)" % (nm, d.get("cycle")), color="#38bdf8", dash=False, grp="entry", strat=key))
                L.append(dict(price=g.sell_price(lots[0]), label="%s EXIT" % nm, color="#ef4444", dash=False, grp="exit", strat=key))
                lv = lots[-1]["level"]
                hold = held
                for i in range(10):
                    lv = g.next_level_below(lv)
                    c = g.lot_size_for(lv, sma2)
                    hold += c * BTC_PER_C
                    L.append(dict(price=round(lv * 2) / 2, label="%s buy %.3f → hold %.3f" % (nm, c * BTC_PER_C, hold), color="#22c55e", dash=False, grp="next", strat=key))
                nb = g.next_level_below(lots[-1]["level"])
                L.append(dict(box=[round(nb, 1), round(g.sell_price(lots[-1]), 1)], label="%s no trading zone" % nm, color="rgba(148,163,184,.18)", grp="box", strat=key))
    except Exception as e:
        print("chart: v11/v12 lines failed:", repr(e), flush=True)
    for x in L:
        if "strat" not in x:
            lb = x.get("label") or ""
            x["strat"] = "v4a" if lb.startswith("V4A") else "v5a" if lb.startswith("V5A") else "manual" if lb.startswith("MY PAPER") else "ladder"
'''
pat = re.compile(r'    return L\n\n\n(# -+ drawings)')
assert len(pat.findall(s)) == 1, 'end of auto() not found exactly once - nothing changed'
s = pat.sub(lambda m: NEW + '    return L\n\n\n' + m.group(1), s)
open(p, 'w', encoding='utf-8').write(s)
print('chartpage.py: strategy lines added')
