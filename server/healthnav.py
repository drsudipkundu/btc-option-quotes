"""Button row shared by the shadow-fleet pages (1-Nov-2026): one strategy at a time, never mixed.
Night-sell fleets live in shadow.py (/health?f=v4|v5), ladder fleets in ladshadow.py (/lhealth?v=v9|v10|v11|v12)."""
TABS = [("v4", "Night v4A-CG-SL", "/health?f=v4", "night"), ("v5", "Night v5A-CG-SL", "/health?f=v5", "night"),
        ("v9", "Ladder v9", "/lhealth?v=v9", "ladder"), ("v10", "Ladder v10", "/lhealth?v=v10", "ladder"),
        ("v11", "Ladder v11", "/lhealth?v=v11", "ladder"), ("v12", "Ladder v12", "/lhealth?v=v12", "ladder")]
COL = {"night": ("#0369a1", "#e0f2fe", "NIGHT OPTION SELL"), "ladder": ("#15803d", "#dcfce7", "BTC LADDER")}

def bar(active):
    kind = next((k for t, _, _, k in TABS if t == active), "night")
    c, light, word = COL[kind]
    h = ['<div style="background:%s;color:#fff;font-weight:700;font-size:12px;padding:6px 10px;border-radius:8px;margin:8px 0">'
         'SHADOW FLEET &middot; %s &middot; paper only</div><div style="display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 10px">' % (c, word)]
    for t, label, url, k in TABS:
        cc, ll, _ = COL[k]
        on = t == active
        h.append('<a href="%s" style="text-decoration:none;padding:7px 12px;border-radius:10px;font-size:13px;font-family:system-ui,sans-serif;'
                 'border:2px solid %s;background:%s;color:%s;font-weight:%s">%s</a>' % (
                     url, cc, cc if on else ll, "#fff" if on else cc, 700 if on else 500, label))
    h.append("</div>")
    return "".join(h)
