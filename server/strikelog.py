#!/usr/bin/env python3
"""Delta India BTC option STRIKE-LIST logger (25-Nov-2026, Sudip). Public data only: no key, no orders, bot untouched.
Purpose: see exactly WHEN Delta lists a new daily expiry, WHEN strikes are added or removed, and how the nearest
far options (hedge candidates) are priced while it happens.
Every 20 s it reads one public ticker call and keeps, for the two nearest expiries:
  strikelog_events.csv  one row each time the set of listed strikes of an expiry changes (added / removed strikes, edges, spot)
  strikelog_edge.csv    one row per 60 s per expiry: spot, lowest and highest put/call strike, distance of each edge from spot (%),
                        bid / ask / sizes of the 3 puts and 3 calls nearest each edge
Files: ~/deltabot/strikelog/ (small; a month is a few MB). 1 contract = 0.001 BTC."""
import csv, json, os, re, socket, sys, time, datetime as dt
import urllib.request, urllib.parse
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

API = "https://api.india.delta.exchange"
OUT = os.path.expanduser(os.environ.get("STRIKELOG_DIR", "~/deltabot/strikelog"))
POLL_S, EDGE_EVERY_S = 20, 60
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
RE = re.compile(r"^([CP])-BTC-(\d+)-(\d{6})$")
EV_COLS = ["ts_ist", "expiry", "spot", "event", "added", "removed", "n_put", "n_call", "put_low", "put_high", "call_low", "call_high"]
ED_COLS = ["ts_ist", "expiry", "spot", "put_low", "put_low_pct", "call_high", "call_high_pct", "n_put", "n_call", "near_edge"]


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "strikelog/1"})
    return json.load(urllib.request.urlopen(req, timeout=10))["result"]


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse(tickers):
    """-> {expiry 'DDMMYY': {'P': {strike: row}, 'C': {strike: row}}}, spot"""
    by, spots = {}, []
    for t in tickers:
        m = RE.match(str(t.get("symbol", "")))
        if not m:
            continue
        q = t.get("quotes") or {}
        row = dict(bid=num(q.get("best_bid")), ask=num(q.get("best_ask")), bsz=num(q.get("bid_size")), asz=num(q.get("ask_size")))
        by.setdefault(m.group(3), {"P": {}, "C": {}})[m.group(1)][float(m.group(2))] = row
        s = num(t.get("spot_price"))
        if s:
            spots.append(s)
    spots.sort()
    return by, (spots[len(spots) // 2] if spots else None)


def exp_key(e):
    return (int(e[4:6]), int(e[2:4]), int(e[0:2]))      # year, month, day


def nearest_two(by):
    return sorted(by, key=exp_key)[:2]


def edge_text(side, d, n=3):
    ks = sorted(d)
    pick = ks[:n] if side == "P" else ks[-n:]
    return ";".join("%d:%s/%s/%s/%s" % (k, d[k]["bid"], d[k]["ask"], d[k]["bsz"], d[k]["asz"]) for k in pick)


class Log:
    def __init__(self, out):
        self.out, self.prev, self.last_edge = out, {}, {}
        os.makedirs(out, exist_ok=True)

    def _w(self, name, cols, row):
        p = os.path.join(self.out, name)
        new = not os.path.exists(p)
        with open(p, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(cols)
            w.writerow(row)

    def step(self, tickers, now):
        by, spot = parse(tickers)
        if not by or not spot:
            return 0
        n = 0
        ts = now.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")
        for e in nearest_two(by):
            P, C = by[e]["P"], by[e]["C"]
            cur = set(("P", k) for k in P) | set(("C", k) for k in C)
            if e not in self.prev:
                ev, add, rem = "FIRST_SEEN", cur, set()
            else:
                add, rem = cur - self.prev[e], self.prev[e] - cur
                ev = "CHANGED" if (add or rem) else ""
            if ev:
                self._w("strikelog_events.csv", EV_COLS, [ts, e, spot, ev,
                        " ".join("%s%d" % x for x in sorted(add)), " ".join("%s%d" % x for x in sorted(rem)),
                        len(P), len(C), min(P) if P else "", max(P) if P else "", min(C) if C else "", max(C) if C else ""])
                n += 1
            self.prev[e] = cur
            if time.time() - self.last_edge.get(e, 0) >= EDGE_EVERY_S:
                self.last_edge[e] = time.time()
                pl, ch = (min(P) if P else None), (max(C) if C else None)
                self._w("strikelog_edge.csv", ED_COLS, [ts, e, spot, pl or "", round(100 * (1 - pl / spot), 2) if pl else "",
                        ch or "", round(100 * (ch / spot - 1), 2) if ch else "", len(P), len(C),
                        "PUT " + edge_text("P", P) + " | CALL " + edge_text("C", C)])
                n += 1
        for e in list(self.prev):
            if e not in by:
                del self.prev[e]
        return n


def main():
    log = Log(OUT)
    while True:
        try:
            tk = get("/v2/tickers", {"contract_types": "call_options,put_options", "underlying_asset_symbols": "BTC"})
            log.step(tk, dt.datetime.now(dt.timezone.utc))
        except Exception as ex:
            sys.stderr.write("strikelog: %s\n" % ex)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
