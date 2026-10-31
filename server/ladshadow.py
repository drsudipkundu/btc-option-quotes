"""Ladder shadow fleet (31-Oct-2026): parameter-health monitor for the LIFO ladders v9 / v10 / v11 / v12.

PAPER ONLY. One process runs ~57 paper copies of the four ladders on the same live Delta India BTCUSD prices.
Each version has a BASE copy (today's settings, started fresh with the fleet) and copies that change ONE value
(gap, sell gap, deep-zone gaps, nested spacing, lot sizes, SMA length, entry filter, 4-hour window, cap,
ER thresholds / lookback / band gaps). Same fill engine as the server paper ladders (bot.Bot: resting maker
orders, filled when a 1-minute candle trades through the price by one tick; maker fee 0.02% + GST; funding
not modelled). Nothing here places orders, sends e-mails or touches the other bots.

Every IST day one row per copy goes to logs/ladshadow_days.csv (booked net, open P&L at the mark, equity,
BTC held). The page /lhealth compares each copy with its version's base day by day (paired difference +
t-score) and shows drawdown and peak BTC held. A ladder needs months (several full cycles) before a verdict.
Run: python ladshadow.py (service ladshadow) | python ladshadow.py --check (indicators + fleet list, no trading)
"""
import os, sys, json, csv, math, time, logging, datetime as dt
from logging.handlers import RotatingFileHandler

HOME = os.environ.get("BOT_HOME", os.path.expanduser("~/deltabot"))
sys.path.insert(0, HOME)
import bot
from ladder import Ladder, TICK, BTC_PER_CONTRACT

SDIR = os.path.join(HOME, "state", "ladshadow")
LDIR = os.path.join(HOME, "logs", "ladshadow")
DAYS_CSV = os.path.join(HOME, "logs", "ladshadow_days.csv")
SUMMARY = os.path.join(HOME, "state", "ladshadow_summary.json")
DCOLS = ["day", "id", "ver", "booked", "open", "equity", "held_btc", "cycle", "mark"]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
log = logging.getLogger("ladshadow")

# ------------------------------------------------------------------ parameters
V9_ZM = [1.0, 1.0, 8.0 / 3, 16.0 / 3, 28.0 / 3]
V9_FL = [73.54, 60.32, 47.09, 33.86]
BASE = dict(g=0.75, sm=1.0, deep=1.0, big=0.004, small=0.002, entry=0.002, sma_n=100, filt=0.95, hwin=240,
            cap=0.28, sp=0.6032, dx=2.0, er_n=10, t=0.2, lo=0.5, t1=0.2, t2=0.4, b=(0.5, 0.75, 1.0))
VER = {"v9": dict(), "v10": dict(cap=0.40), "v11": dict(), "v12": dict()}


def fleet():
    F = []

    def add(ver, cid, label, grp, **over):
        F.append((cid, ver, label, grp, dict(BASE, **dict(VER[ver], **over))))
    for v in ("v9", "v10"):
        n = v
        cap0 = 0.28 if v == "v9" else 0.40
        add(v, n + "_base", "BASE = %s today" % n, "base")
        add(v, n + "_g050", "zone-1/2 gap 0.5%", "gap", g=0.5)
        add(v, n + "_g100", "zone-1/2 gap 1.0%", "gap", g=1.0)
        if v == "v9":
            add(v, n + "_d075", "deep-zone gaps x0.75 (1.5/3/5.25%)", "deep", deep=0.75)
            add(v, n + "_d125", "deep-zone gaps x1.25 (2.5/5/8.75%)", "deep", deep=1.25)
        else:
            add(v, n + "_sp050", "next ladder starts at 50% (not 60.32%)", "sp", sp=0.5)
            add(v, n + "_sp070", "next ladder starts at 70%", "sp", sp=0.7)
            add(v, n + "_dx1", "no double lots in ladders 3-4", "dx", dx=1.0)
            add(v, n + "_dx3", "triple lots in ladders 3-4", "dx", dx=3.0)
        add(v, n + "_sm080", "sell gap x0.8 (sell sooner)", "sm", sm=0.8)
        add(v, n + "_sm125", "sell gap x1.25 (sell later)", "sm", sm=1.25)
        add(v, n + "_lot2", "lots 0.002 always (no SMA sizing)", "lot", big=0.002)
        add(v, n + "_lot4", "lots 0.004 always (no SMA sizing)", "lot", small=0.004)
        add(v, n + "_sma50", "lot sizing on SMA50", "sma", sma_n=50)
        add(v, n + "_sma150", "lot sizing on SMA150", "sma", sma_n=150)
        add(v, n + "_f090", "entry within 10% of 4-h high", "filt", filt=0.90)
        add(v, n + "_f100", "entry only at a new 4-h high", "filt", filt=1.0)
        add(v, n + "_h1", "entry high over 1 h (not 4 h)", "hwin", hwin=60)
        add(v, n + "_h12", "entry high over 12 h", "hwin", hwin=720)
        add(v, n + "_capA", "cap %.2f BTC" % (cap0 - 0.08), "cap", cap=round(cap0 - 0.08, 3))
        add(v, n + "_capB", "cap %.2f BTC" % (cap0 + 0.08), "cap", cap=round(cap0 + 0.08, 3))
    add("v11", "v11_base", "BASE = v11 today", "base")
    add("v11", "v11_t015", "choppy if ER < 0.15", "t", t=0.15)
    add("v11", "v11_t025", "choppy if ER < 0.25", "t", t=0.25)
    add("v11", "v11_lo040", "choppy gap 0.4%", "lo", lo=0.4)
    add("v11", "v11_lo060", "choppy gap 0.6%", "lo", lo=0.6)
    add("v11", "v11_g100", "normal gap 1.0%", "gap", g=1.0)
    add("v11", "v11_n7", "ER over 7 days", "ern", er_n=7)
    add("v11", "v11_n14", "ER over 14 days", "ern", er_n=14)
    add("v11", "v11_sm080", "sell gap x0.8", "sm", sm=0.8)
    add("v11", "v11_sm125", "sell gap x1.25", "sm", sm=1.25)
    add("v12", "v12_base", "BASE = v12 mode 1 today", "base")
    add("v12", "v12_t1015", "band 1 if ER < 0.15", "t1", t1=0.15)
    add("v12", "v12_t1025", "band 1 if ER < 0.25", "t1", t1=0.25)
    add("v12", "v12_t2030", "band 3 if ER > 0.30", "t2", t2=0.30)
    add("v12", "v12_t2050", "band 3 if ER > 0.50", "t2", t2=0.50)
    add("v12", "v12_b1040", "band 1 gap 0.4%", "b1", b=(0.4, 0.75, 1.0))
    add("v12", "v12_b1060", "band 1 gap 0.6%", "b1", b=(0.6, 0.75, 1.0))
    add("v12", "v12_b3090", "band 3 gap 0.9%", "b3", b=(0.5, 0.75, 0.9))
    add("v12", "v12_b3125", "band 3 gap 1.25%", "b3", b=(0.5, 0.75, 1.25))
    add("v12", "v12_n7", "ER over 7 days", "ern", er_n=7)
    add("v12", "v12_n14", "ER over 14 days", "ern", er_n=14)
    add("v12", "v12_sm080", "sell gap x0.8", "sm", sm=0.8)
    add("v12", "v12_sm125", "sell gap x1.25", "sm", sm=1.25)
    return F


GROUPS = {"gap": "Zone-1/2 gap (0.75%)", "deep": "Deep-zone gaps (2/4/7%)", "sp": "Nested spacing (60.32%)",
          "dx": "Lots in ladders 3-4 (x2)", "sm": "Sell gap (= buy gap)", "lot": "Lot sizing (0.004 above SMA / 0.002 below)",
          "sma": "SMA length for lot sizing (100)", "filt": "Entry filter (within 5% of the high)",
          "hwin": "Entry high window (4 h)", "cap": "Position cap", "t": "Choppy threshold (ER < 0.2)",
          "lo": "Choppy gap (0.5%)", "ern": "ER lookback (10 days)", "t1": "Band-1 threshold (ER < 0.2)",
          "t2": "Band-3 threshold (ER > 0.4)", "b1": "Band-1 gap (0.5%)", "b3": "Band-3 gap (1.0%)"}


# ------------------------------------------------------------------ the ladder with parameters
class PLadder(Ladder):
    def __init__(self, ver, P, scale=1.0):
        Ladder.__init__(self, scale=scale, brake_btc=P["cap"], entry_filter=P["filt"])
        self.ver, self.P = ver, P
        self.entry_c = self._c(P["entry"])
        self.big_c = self._c(P["big"])
        self.small_c = self._c(P["small"])
        self.er = None
        self.base = P["g"]
        if ver == "v10":
            f = P["sp"]
            self.floors = []
            self.zm = []
            for k in range(4):
                self.floors += [73.54 * f ** k, 60.32 * f ** k]
                self.zm += [f ** k, f ** k]
        else:
            self.floors = list(V9_FL)
            self.zm = [1.0, 1.0] + [m * P["deep"] for m in V9_ZM[2:]]

    def zone(self, level):
        pct = level / self.entry * 100.0
        for i, f in enumerate(self.floors):
            if pct > f:
                return i + 1
        return len(self.floors) + 1

    def base_gap(self):
        P = self.P
        if self.ver == "v11":
            return self.base
        if self.ver == "v12":
            if self.er is None:
                return P["b"][1]
            return P["b"][0] if self.er < P["t1"] else (P["b"][1] if self.er < P["t2"] else P["b"][2])
        return P["g"]

    def gaps(self):
        b = [self.base_gap() * m for m in self.zm]
        return b, [x * self.P["sm"] for x in b]

    def next_level_below(self, level):
        z = self.zone(level)
        nz = len(self.zm)
        if self.ver == "v10" and z > nz:
            return 0.0
        nxt = level - self.entry * self.gaps()[0][min(z, nz) - 1] / 100.0
        for f in self.floors:
            fl = self.entry * f / 100.0
            if level > fl + 1e-9 and nxt < fl - 1e-9:
                nxt = fl
                break
        if self.ver == "v10" and nxt < self.entry * self.floors[-1] / 100.0 - 1e-6:
            return 0.0
        return max(nxt, 0.0)

    def sell_price(self, lot):
        z = min(self.zone(lot["level"]), len(self.zm))
        return lot["buy_price"] + self.entry * self.gaps()[1][z - 1] / 100.0

    def lot_size_for(self, level, sma):
        c = self.big_c if (sma is not None and level > sma) else self.small_c
        if self.ver == "v10" and self.entry > 0 and level > 0 and self.zone(level) >= 5:
            c = max(1, int(round(c * self.P["dx"])))
        return c

    def start_cycle(self, price, c):
        if self.ver == "v11":
            self.base = self.P["lo"] if (self.er is not None and self.er < self.P["t"]) else self.P["g"]
        Ladder.start_cycle(self, price, c)

    def to_dict(self):
        d = Ladder.to_dict(self)
        d.update(er=self.er, base=self.base)
        return d

    def from_dict(self, d):
        Ladder.from_dict(self, d)
        self.er = d.get("er")
        self.base = d.get("base", self.P["g"])


# ------------------------------------------------------------------ shared, cached market data
class CachedFeed:
    def __init__(self):
        self.f = bot.Feed()
        self.tk, self.tk_ts = None, 0
        self.m1, self.m1_ts = {}, 0
        self.d1, self.d1_ts = [], 0

    def ticker(self):
        if time.time() - self.tk_ts > 2:
            self.tk, self.tk_ts = self.f.ticker(), time.time()
        return self.tk

    def candles(self, res, start, end):
        now = time.time()
        if res == "1d":
            if now - self.d1_ts > 300:
                self.d1, self.d1_ts = self.f.candles("1d", now - 200 * 86400, now), now
            return [x for x in self.d1 if start <= x["time"] <= end]
        if now - self.m1_ts > 2:
            for x in self.f.candles("1m", now - 900, now):
                self.m1[int(x["time"])] = x
            self.m1_ts = now
        lo = min(self.m1) if self.m1 else now
        if start < lo - 60:
            for x in self.f.candles("1m", start, min(end, lo)):
                self.m1.setdefault(int(x["time"]), x)
        for k in [k for k in self.m1 if k < now - 13 * 3600]:
            del self.m1[k]
        return [self.m1[k] for k in sorted(self.m1) if start <= k <= end]


class Null:
    def send(self, *a, **k):
        pass


# ------------------------------------------------------------------ one paper copy
class Copy(bot.Bot):
    def __init__(self, cid, ver, label, grp, P, feed):
        self.cid, self.ver, self.label, self.grp, self.P = cid, ver, label, grp, P
        self.feed, self.n, self.clock = feed, Null(), time.time
        self.ladder = PLadder(ver, P)
        self.margin, self.fill_mode = TICK, "through"
        self.orders, self.next_oid, self.prog = {}, 1, None
        self.sma = self.high4h = None
        self.ind_ts = 0
        self.paused = False
        self.last_summary_day = None
        self.last_beat = self.err_count = self.last_err_mail = 0
        self.booked = 0.0
        self.peak_held = 0
        self.statefile = os.path.join(SDIR, "%s.json" % cid)
        self.tradesfile = os.path.join(LDIR, "trades_%s.csv" % cid)
        self.saved_ts = 0
        os.makedirs(SDIR, exist_ok=True)
        os.makedirs(LDIR, exist_ok=True)
        self.load()

    def save(self, force=False):
        if not force and time.time() - self.saved_ts < 20:
            return
        d = {"ladder": self.ladder.to_dict(), "orders": self.orders, "next_oid": self.next_oid, "prog": self.prog,
             "booked": self.booked, "peak_held": self.peak_held}
        tmp = self.statefile + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, self.statefile)
        self.saved_ts = time.time()

    def load(self):
        if not os.path.exists(self.statefile):
            return
        d = json.load(open(self.statefile))
        self.ladder.from_dict(d["ladder"])
        self.orders = {int(k): v for k, v in d["orders"].items()}
        self.next_oid, self.prog = d["next_oid"], d.get("prog")
        self.booked, self.peak_held = d.get("booked", 0.0), d.get("peak_held", 0)

    def log_trade(self, event, side, c, price, pnl=0.0, note=""):
        new = not os.path.exists(self.tradesfile)
        fee = c * BTC_PER_CONTRACT * price * bot.FEE_RATE
        self.booked += pnl - fee
        self.peak_held = max(self.peak_held, self.ladder.held())
        with open(self.tradesfile, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time_ist", "event", "cycle", "side", "contracts", "price", "fee_usd", "pnl_usd",
                            "lots_after", "held_contracts", "note"])
            w.writerow([bot.ist().strftime("%Y-%m-%d %H:%M:%S"), event, self.ladder.cycle, side, c, "%.1f" % price,
                        "%.4f" % fee, "%.4f" % pnl, len(self.ladder.lots), self.ladder.held(), note])
        self.save(force=True)
        return fee

    def refresh_indicators(self, now):
        if now - self.ind_ts < 60 and self.high4h is not None:
            return
        P = self.P
        c1 = self.feed.candles("1m", now - P["hwin"] * 60, now)
        if c1:
            self.high4h = max(float(x["high"]) for x in c1)
        day0 = int(now // 86400) * 86400
        cd = [x for x in self.feed.candles("1d", day0 - 200 * 86400, now) if x["time"] < day0]
        if len(cd) >= 20:
            last = cd[-P["sma_n"]:]
            self.sma = sum(float(x["close"]) for x in last) / len(last)
        n = P["er_n"]
        if len(cd) >= n + 1:
            cl = [float(x["close"]) for x in cd[-(n + 1):]]
            path = sum(abs(cl[i] - cl[i - 1]) for i in range(1, n + 1))
            self.ladder.er = (abs(cl[-1] - cl[0]) / path) if path > 0 else 0.0
        self.ind_ts = now

    def step(self):
        now = time.time()
        bid, ask, mark = self.feed.ticker()
        self.refresh_indicators(now)
        self.process_candles(now, bid, ask)
        if self.ladder.active:
            self.replan(bid, ask)
        else:
            self.entry_logic(bid, ask, now)
        self.save()

    def snap(self, mark):
        L = self.ladder
        op = sum((mark - l["buy_price"]) * l["c"] * BTC_PER_CONTRACT for l in L.lots)
        return dict(id=self.cid, ver=self.ver, label=self.label, grp=self.grp, cycle=L.cycle, active=L.active,
                    lots=len(L.lots), held_btc=L.held() * BTC_PER_CONTRACT, peak_btc=self.peak_held * BTC_PER_CONTRACT,
                    booked=round(self.booked, 4), open=round(op, 4), equity=round(self.booked + op, 4),
                    entry=L.entry, gap=round(L.gaps()[0][0], 4), er=L.er)


# ------------------------------------------------------------------ fleet loop
def day_rows(copies, mark, day):
    new = not os.path.exists(DAYS_CSV)
    with open(DAYS_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(DCOLS)
        for c in copies:
            s = c.snap(mark)
            w.writerow([day, s["id"], s["ver"], "%.4f" % s["booked"], "%.4f" % s["open"], "%.4f" % s["equity"],
                        "%.3f" % s["held_btc"], s["cycle"], "%.1f" % mark])


def main():
    for d in (SDIR, LDIR):
        os.makedirs(d, exist_ok=True)
    fh = RotatingFileHandler(os.path.join(HOME, "logs", "ladshadow.log"), maxBytes=2_000_000, backupCount=2)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    for lg in (log, bot.log):
        lg.setLevel(logging.INFO)
        lg.addHandler(fh)
    feed = CachedFeed()
    copies = [Copy(cid, ver, label, grp, P, feed) for cid, ver, label, grp, P in fleet()]
    if "--check" in sys.argv:
        bid, ask, mark = feed.ticker()
        for c in copies:
            c.refresh_indicators(time.time())
            print("%-12s %-4s sma%-3d=%s high=%s er=%s gaps=%s cap=%d" % (
                c.cid, c.ver, c.P["sma_n"], "%.0f" % c.sma if c.sma else None, c.high4h,
                ("%.3f" % c.ladder.er) if c.ladder.er is not None else None,
                [round(x, 3) for x in c.ladder.gaps()[0]], c.ladder.brake))
        print("copies:", len(copies), "mark", mark)
        return
    st_path = os.path.join(SDIR, "_fleet.json")
    st = json.load(open(st_path)) if os.path.exists(st_path) else {}
    log.info("ladder shadow fleet started: %d copies", len(copies))
    last_sum = 0
    while True:
        errs = 0
        for c in copies:
            try:
                c.step()
            except Exception as e:
                errs += 1
                log.error("[%s] step failed: %s", c.cid, e)
        try:
            mark = feed.ticker()[2]
            today = dt.datetime.now(IST).strftime("%Y-%m-%d")
            if st.get("day") != today:
                day_rows(copies, mark, st.get("day") or ("start " + today))
                st["day"] = today
                json.dump(st, open(st_path, "w"))
            if time.time() - last_sum > 30:
                tmp = SUMMARY + ".tmp"
                json.dump(dict(ts=time.time(), mark=mark, copies=[c.snap(mark) for c in copies]), open(tmp, "w"))
                os.replace(tmp, SUMMARY)
                last_sum = time.time()
        except Exception as e:
            errs += 1
            log.error("fleet bookkeeping failed: %s", e)
        time.sleep(3 if errs == 0 else 15)


# ------------------------------------------------------------------ page (/lhealth on the control page)
def _rows(p):
    try:
        return list(csv.DictReader(open(p)))
    except Exception:
        return []


def _tscore(d):
    n = len(d)
    if n < 3:
        return 0.0
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd > 0 else 0.0


def page_html():
    try:
        S = json.load(open(SUMMARY))
    except Exception:
        S = {"copies": [], "mark": 0, "ts": 0}
    D = [r for r in _rows(DAYS_CSV) if not r["day"].startswith("start")]
    eq = {}
    for r in D:
        eq.setdefault(r["id"], {})[r["day"]] = float(r["equity"])

    def daily(cid):
        e = eq.get(cid, {})
        ks = sorted(e)
        return {ks[i]: e[ks[i]] - e[ks[i - 1]] for i in range(1, len(ks))}

    def mdd(cid):
        e = [eq.get(cid, {})[k] for k in sorted(eq.get(cid, {}))]
        pk, dd = 0.0, 0.0
        for x in e:
            pk = max(pk, x)
            dd = min(dd, x - pk)
        return dd
    esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;")
    h = ["<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<title>Ladder health</title><style>body{font-family:system-ui,Arial;margin:12px;color:#0f172a;background:#f8fafc}",
         "table{border-collapse:collapse;font-size:13px;margin-bottom:18px;width:100%}td,th{border-bottom:1px solid #e2e8f0;padding:4px 6px;text-align:right}",
         "td:first-child,th:first-child{text-align:left}th{background:#e2e8f0}tr.g td{background:#f1f5f9;font-weight:600;text-align:left}",
         ".base td{background:#eef6ff;font-weight:600}.pos{color:#15803d}.neg{color:#b91c1c}.wrap{overflow-x:auto}</style></head><body>",
         "<a href='/'>&larr; My Bots</a> &nbsp; <a href='/health'>Night-sell health</a>",
         "<h2>Ladder health (shadow fleet)</h2>",
         "<p>%d paper copies of the ladders v9, v10, v11 and v12 trade the same live Delta prices, each with ONE value changed. "
         "Every version has its own BASE copy, started fresh with the fleet, so all copies of a version are compared from the same start. "
         "Paper only, never real orders. Fees included, funding not modelled. Mark now %.1f. "
         "A ladder needs months (several full cycles) before a verdict; until then every row says <b>collecting</b>.</p>" % (len(S["copies"]), S.get("mark") or 0)]
    byver = {}
    for c in S["copies"]:
        byver.setdefault(c["ver"], []).append(c)
    for ver in ("v9", "v10", "v11", "v12"):
        cs = byver.get(ver, [])
        if not cs:
            continue
        base = next((c for c in cs if c["grp"] == "base"), None)
        bd = daily(base["id"]) if base else {}
        h.append("<h3>%s</h3><div class='wrap'><table><tr><th>Copy</th><th>Cycle</th><th>BTC held</th><th>Peak BTC</th><th>Booked $</th>"
                 "<th>Open $</th><th>Equity $</th><th>vs base $</th><th>Days</th><th>t-score</th><th>Max DD $</th><th>Verdict</th></tr>" % ver.upper())
        grp = None
        for c in cs:
            if c["grp"] != grp and c["grp"] != "base":
                grp = c["grp"]
                h.append("<tr class='g'><td colspan='12'>%s</td></tr>" % esc(GROUPS.get(grp, grp)))
            dd = daily(c["id"])
            common = [k for k in dd if k in bd]
            diff = [dd[k] - bd[k] for k in common]
            t = _tscore(diff) if c["grp"] != "base" else 0.0
            vs = c["equity"] - base["equity"] if (base and c["grp"] != "base") else 0.0
            m, mb = mdd(c["id"]), mdd(base["id"]) if base else 0.0
            verdict = "collecting"
            if c["grp"] != "base" and len(common) >= 90:
                verdict = "RESET CANDIDATE" if (t >= 2 and m >= mb * 1.1) else ("worse" if t <= -2 else "no clear edge")
            cls = "pos" if vs > 0 else ("neg" if vs < 0 else "")
            h.append("<tr%s><td>%s</td><td>%s</td><td>%.3f</td><td>%.3f</td><td>%.2f</td><td>%.2f</td><td>%.2f</td>"
                     "<td class='%s'>%s</td><td>%d</td><td>%s</td><td>%.2f</td><td>%s</td></tr>" % (
                         " class='base'" if c["grp"] == "base" else "", esc(c["label"]), c["cycle"], c["held_btc"], c["peak_btc"],
                         c["booked"], c["open"], c["equity"], cls, ("%+.2f" % vs) if c["grp"] != "base" else "", len(common),
                         ("%.1f" % t) if c["grp"] != "base" else "", m, verdict if c["grp"] != "base" else ""))
        h.append("</table></div>")
    h.append("<p>Equity = booked net profit + open P&amp;L of held lots at the mark. vs base = equity difference now. "
             "t-score = how consistently the copy beat its base day by day (paired, daily equity change). "
             "RESET CANDIDATE = 90+ days, t-score 2 or more and a max drawdown no more than 10% deeper than the base: a prompt to re-test "
             "that value on the long backtest, not an automatic change. Files: logs/ladshadow_days.csv, logs/ladshadow/trades_*.csv.</p></body></html>")
    return "".join(h)


if __name__ == "__main__":
    main()
