"""Strategy details + side-by-side comparison page (/strategies), 1-Nov-2026.
Every strategy's full logic is hidden until "Details" is tapped; tick "Compare" on 2+ strategies and press
"Compare selected" for a table (same rows for all, like a car/phone comparison site). One ticked = its full details.
Read-only page: it never changes a strategy."""
import os, sys, json, csv, html

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)

ROWS = [("market", "Market & instrument"), ("entry", "Entry time & condition"), ("side", "Which side / level"),
        ("strike", "Strike / level rule"), ("size", "Size & sizing rules"), ("rules", "Slope / volatility / ER rules"),
        ("exits", "Exits"), ("guards", "Guards & stops"), ("account", "Account & mode"), ("results", "Results so far")]

NIGHT_COMMON = dict(
    market="Delta India BTC daily options (next-day expiry 17:30 IST); quotes from Delta public data",
    entry="23:30-23:58 IST every night. Trades only if yesterday moved at least 0.5% (main night) or its range was big enough (quiet-day guard: high-low >= HV14 daily sigma)",
    side="Previous daily close above SMA50 -> sell a PUT, else sell a CALL (the side away from the trend)",
    strike="Normal night: nearest listed strike 2.5% away. Moved night (HV14 > 0.283): 1.4 x daily sigma away. Skips strikes that Delta has capped (jumps further out, max 1,200 points). Sells only if the BID is at least $10",
    exits="90% buy-back once the option has lost 90% of its value (checked after midnight); everything left is closed at 17:20 IST next day",
    guards="Crash guard: if BTC moves 2 x ATR14 against the sale, buys the same quantity of an option 4% beyond (insurance). $10 bid floor. One sale per side per night. SMART SELL on every sale: mid-price offer 60 s, then sells into the bids down to 80% of the start bid (never < $10), 3 retries 3 min apart, up to 4 strikes further out, else skip (paper copies: filled only against the real Delta order book)")

S = {
    "v4a": dict(NIGHT_COMMON, title="Night v4A-CG", kind="night",
                size="Base 0.02 BTC. Main night 1x (moved 2x). Quiet night 1x. IV boost +0.5x (moved +1x) when the option IV >= 1.4 x HV7",
                rules="No slope rule (full size every night)"),
    "v4asl": dict(NIGHT_COMMON, title="Night v4A-CG-SL (slope half)", kind="night",
                  size="Base 0.02 BTC. Main night 1x (moved 2x). Quiet night 1x. IV boost +0.5x (moved +1x) when IV >= 1.4 x HV7",
                  rules="Slope rule: MA50 slope speed-up (acceleration) above 0.123 on the last completed day -> EVERY sale that night is half size"),
    "nlive": dict(NIGHT_COMMON, title="Night v4A-CG-SL LIVE MONEY", kind="night",
                  size="Base 0.02 BTC (same multiples as v4A-CG-SL). Size guard: max 0.05 BTC per order, 0.15 BTC open",
                  rules="Slope rule as v4A-CG-SL (half size above 0.123)",
                  exits=NIGHT_COMMON["exits"] + ". Buy-back pays up to 1.5x the ask; 17:20 exit up to 3x, Delta settles anything left at 17:30",
                  guards=NIGHT_COMMON["guards"] + ". Position check every minute: any mismatch stops new sales"),
    "v5a": dict(NIGHT_COMMON, title="Night v5A-CG", kind="night",
                size="Base 0.02 BTC. Main night 1x (moved 3x). Quiet night 1x. Extra OPPOSITE-side leg 1x when HV14 >= HV365. IV boost +0.5x on normal (not moved) nights",
                rules="No slope rule"),
    "v5asl": dict(NIGHT_COMMON, title="Night v5A-CG-SL (slope half)", kind="night",
                  size="Base 0.02 BTC. Main night 1x (moved 3x). Extra opposite leg 1x when HV14 >= HV365. IV boost +0.5x on normal nights",
                  rules="Slope rule: speed-up above 0.123 -> every sale half size"),
}
LAD_COMMON = dict(
    market="Delta India BTCUSD perpetual future (long only, no leverage)",
    entry="Starts a cycle when price is within 5% of the 4-hour high (entry filter 95%); first buy = entry lot",
    side="Buys only (long). LIFO: the newest lot is sold first",
    exits="Each lot sells at its own buy price + the gap; the cycle ends when the last lot is sold, then a new cycle starts. "
          "CALL LEG (v9 CALL v3 rules, SMART SELL): from 17:35 sell the next-day call with delta ~0.03 if its strike is > 5% above BTC, "
          "qty = held lots whose sell target is at/above the strike; extra call (2x, max 0.3 BTC) 17:35-17:50 when yesterday's close <= SMA100, "
          "extra stopped out at strike x1.05; covered calls bought back lot by lot as covered lots sell; everything bought back 17:20-17:30 on expiry day",
    guards="Brake: no buys beyond the BTC cap. Zone floors (no buys below the last floor). No stop-loss, no forced exit. Resting maker orders (paper fills)")
S.update({
    "ladder": dict(LAD_COMMON, title="Ladder v9 (paper on server)", kind="ladder",
                   strike="Buy gaps 0.75 / 0.75 / 2 / 4 / 7 % of entry in zones 1-5; floors 73.54 / 60.32 / 47.09 / 33.86 %",
                   size="0.004 BTC per step above SMA100, 0.002 below. Brake 0.28 BTC",
                   rules="Fixed gaps (no ER, no slope)"),
    "lv10": dict(LAD_COMMON, title="Ladder v10 nested (paper)", kind="ladder",
                 strike="4 ladders x 2 zones. Gaps 0.75/0.75/0.4524/0.4524/0.2729/0.2729/0.1646/0.1646 % of entry; floors 73.54/60.32/44.36/36.38/26.76/21.95/16.14/13.24",
                 size="Zones 1-4: 0.004 / 0.002 BTC by SMA100; zones 5-8 double. Entry 0.002. Cap 0.40 BTC",
                 rules="Fixed gaps (no ER)"),
    "lv11": dict(LAD_COMMON, title="Ladder v11 (ER gap at cycle start)", kind="ladder",
                 strike="Like v9, but zone-1 gap set at cycle start: ER10 < 0.2 -> 0.5 %, else 0.75 % (fixed for the cycle)",
                 size="As v9: 0.004 / 0.002 BTC by SMA100, brake 0.28 BTC",
                 rules="Efficiency ratio ER10 of the last completed day, read once at cycle start"),
    "lv12": dict(LAD_COMMON, title="Ladder v12 (ER gap daily, mode 1)", kind="ladder",
                 strike="Gap re-read every day: ER10 < 0.2 -> 0.5 %, < 0.4 -> 0.75 %, else 1.0 %; zone multipliers 1, 1, 8/3, 16/3, 28/3; each lot remembers its own buy price",
                 size="As v9: 0.004 / 0.002 BTC by SMA100, brake 0.28 BTC",
                 rules="ER10 daily (last completed day), sell gap = buy gap"),
})

def _results(sid):
    try:
        if S[sid]["kind"] == "night":
            st = json.load(open(os.path.join(HOME, "state", "night_%s.json" % sid)))
            return "%.2f USD so far (fees included; paper)" % st.get("total_pnl", 0.0)
        f = "trades_paper.csv" if sid == "ladder" else "trades_%s.csv" % sid
        tot, n = 0.0, 0
        for r in csv.DictReader(open(os.path.join(HOME, "logs", f))):
            tot += (float(r.get("pnl_usd") or 0) if r.get("event") == "SELL" else 0.0) - float(r.get("fee_usd") or 0)
            n += r.get("event") == "SELL"
        cp = 0.0
        try:
            for r in csv.DictReader(open(os.path.join(HOME, "logs", "calls_%s.csv" % sid))):
                cp += float(r.get("pnl_usd") or 0)
        except Exception:
            pass
        return "%.2f USD booked, %d sells (fees included); call leg %.2f USD" % (tot, n, cp)
    except Exception:
        return "no results yet"

def _account(sid, ctl):
    c = ctl.get(sid, {})
    mode = c.get("mode", "paper")
    if sid == "nlive":
        try:
            cfg = json.load(open(os.path.join(HOME, "state", "night_live_cfg.json")))
            return "LIVE MONEY on Delta sub-account %s (%s), state %s" % (cfg.get("acct"), "armed" if cfg.get("armed") else "disarmed", c.get("state", "?"))
        except Exception:
            return "LIVE MONEY (config not readable)"
    return "%s, state %s" % ("PAPER (no real orders)" if mode == "paper" else mode.upper(), c.get("state", "?"))

def page_html():
    try:
        import control
        ctl = control.load()
    except Exception:
        ctl = {}
    E = html.escape
    data = {}
    for sid, d in S.items():
        row = {k: d.get(k, "-") for k, _ in ROWS}
        row["account"] = _account(sid, ctl)
        row["results"] = _results(sid)
        data[sid] = dict(title=d["title"], kind=d["kind"], rows=row)
    h = ['<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         '<title>Strategy details</title><style>*{box-sizing:border-box}body{font-family:system-ui,sans-serif;margin:0;background:#f4f5f7;color:#1c2430}'
         '.w{max-width:1000px;margin:0 auto;padding:12px 14px 60px}h1{font-size:20px;margin:6px 0}.m{color:#6b7684;font-size:12px}'
         '.card{background:#fff;border-radius:12px;padding:12px 14px;margin:10px 0;box-shadow:0 1px 3px #0001;border-left:6px solid #0284c7}'
         '.card.ladder{border-left-color:#15803d}.card.live{border-left-color:#ea580c}.t{font-weight:700;font-size:15px}'
         '.top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}'
         'button{border:0;border-radius:8px;padding:7px 12px;font-size:13px;cursor:pointer;background:#e5e8ec}'
         'button.go{background:#1c2430;color:#fff}label{font-size:13px;white-space:nowrap}'
         'dl{margin:8px 0 0}dt{font-size:11px;color:#6b7684;text-transform:uppercase;letter-spacing:.04em;margin-top:8px}dd{margin:2px 0 0;font-size:14px}'
         '.cmp{overflow-x:auto;background:#fff;border-radius:12px;padding:10px;box-shadow:0 1px 3px #0001;margin:12px 0}'
         'table{border-collapse:collapse;font-size:13px;min-width:600px}td,th{border-bottom:1px solid #e5e8ec;padding:7px 8px;vertical-align:top;text-align:left}'
         'th{background:#1c2430;color:#fff;position:sticky;top:0}td:first-child{font-weight:700;background:#f8fafc;width:150px}'
         '.bar{position:sticky;bottom:0;background:#fff;padding:10px;border-top:1px solid #e5e8ec;display:flex;gap:8px;justify-content:center}'
         'a{color:#0369a1}</style></head><body><div class="w"><p><a href="/">&larr; My Bots</a></p>'
         '<h1>Strategy details &amp; compare</h1><p class="m">Tap <b>Details</b> to open one strategy. Tick <b>Compare</b> on two or more and press '
         '<b>Compare selected</b> for a side-by-side table. Blue = night option sell, green = ladder, orange = live money. Read-only page.</p>'
         '<div id="cmp"></div>']
    for sid, d in data.items():
        cls = "card live" if sid == "nlive" else ("card ladder" if d["kind"] == "ladder" else "card")
        h.append('<div class="%s"><div class="top"><div class="t">%s</div><div><label><input type="checkbox" class="pick" value="%s"> Compare</label> '
                 '<button onclick="tg(\'%s\')">Details</button></div></div><div id="d_%s" style="display:none"><dl>' % (cls, E(d["title"]), sid, sid, sid))
        for k, lab in ROWS:
            h.append("<dt>%s</dt><dd>%s</dd>" % (E(lab), E(d["rows"][k])))
        h.append("</dl></div></div>")
    h.append('<div class="bar"><button class="go" onclick="cmp()">Compare selected</button><button onclick="clr()">Clear</button></div></div>')
    h.append("<script>var D=%s,R=%s;" % (json.dumps(data), json.dumps(ROWS)))
    h.append("""function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')}
function tg(s){var e=document.getElementById('d_'+s);e.style.display=e.style.display=='none'?'block':'none'}
function clr(){document.querySelectorAll('.pick').forEach(function(c){c.checked=false});document.getElementById('cmp').innerHTML=''}
function cmp(){var ids=[];document.querySelectorAll('.pick').forEach(function(c){if(c.checked)ids.push(c.value)});
 var o=document.getElementById('cmp');if(!ids.length){o.innerHTML='<p class=m>Tick at least one strategy.</p>';return}
 if(ids.length==1){document.getElementById('d_'+ids[0]).style.display='block';document.getElementById('d_'+ids[0]).scrollIntoView();o.innerHTML='';return}
 var h='<div class=cmp><table><tr><th>&nbsp;</th>';ids.forEach(function(i){h+='<th>'+esc(D[i].title)+'</th>'});h+='</tr>';
 R.forEach(function(r){h+='<tr><td>'+esc(r[1])+'</td>';ids.forEach(function(i){h+='<td>'+esc(D[i].rows[r[0]])+'</td>'});h+='</tr>'});
 o.innerHTML=h+'</table></div>';o.scrollIntoView()}</script></body></html>""")
    return "".join(h).encode("utf-8")
