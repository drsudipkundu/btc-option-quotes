"""Smart Sell job engine (1-Nov-2026), shared by the ladder call legs - paper AND live.
Same rules as the night seller: 1) polite offer at the mid for 60 s (first strike only); 2) sell into the bids down to the
walk-away price = 80% of the start bid (never below the floor); 3) 3 retries 3 min apart; 4) up to 4 strikes further out
(one sweep each); 5) stop, keep what is sold, skip the rest. Non-blocking: run_job() is called every tick.
A job is a plain dict (saved in the bot's JSON state). An executor does the actual selling:
  PaperExec - fills only against Delta's real order book (strict), never places orders.
  LiveExec  - real limit orders on a Delta sub-account (polite = resting limit at the mid; sweep = limit at the
              worst acceptable visible bid, cancelled after a few seconds)."""
import math, time

C = 0.001
SS = dict(walk=0.8, polite_s=60, retries=3, retry_wait_s=180, further=4, max_job_s=1800, tick=0.5, fill_wait_s=6)
_BOOK = {}

def up(p, tick):
    return round(math.ceil(p / tick - 1e-9) * tick, 8)

def public_book(sym, ttl=3.0):
    hit = _BOOK.get(sym)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    import delta_api as d
    r = d.public("/v2/l2orderbook/%s" % sym, {"depth": 20})["result"]
    bids = sorted([(float(x["price"]), int(x["size"])) for x in (r.get("buy") or [])], key=lambda x: -x[0])
    asks = sorted([(float(x["price"]), int(x["size"])) for x in (r.get("sell") or [])], key=lambda x: x[0])
    _BOOK[sym] = (time.time(), (bids, asks))
    return bids, asks

def new_job(key, side, o0, want, chain, ts, floor, note="", further=None):
    """o0 = chosen option (dict with sym/strike/exp/typ/bid/ask). chain = same-expiry options for further strikes."""
    k = SS["further"] if further is None else further
    same = [o for o in chain if o["typ"] == side and o["exp"] == o0["exp"] and not o.get("ro")]
    if side == "CE":
        out = sorted([o for o in same if o["strike"] > o0["strike"]], key=lambda o: o["strike"])
    else:
        out = sorted([o for o in same if o["strike"] < o0["strike"]], key=lambda o: -o["strike"])
    return dict(key=key, side=side, exp=o0["exp"], want=int(want), left=int(want), fills=[], floor=floor,
                cands=[o0["strike"]] + [o["strike"] for o in out[:k]], i=0, phase="start", t0=ts, t_end=0,
                rounds=0, ref=0, walk=0, mid=0, oid=None, ofilled=0, note=note, done=False)

def _find(chain, side, k, exp):
    for o in chain:
        if o["typ"] == side and o["exp"] == exp and abs(o["strike"] - k) < 1e-6:
            return o
    return None

def run_job(J, chain, ts, ex):
    """advance one job; returns True when finished (J['done'])."""
    if J["done"]:
        return True
    while J["left"] > 0 and J["i"] < len(J["cands"]):
        if ts - J["t0"] > SS["max_job_s"]:
            break
        o = _find(chain, J["side"], J["cands"][J["i"]], J["exp"])
        if not o:
            J["i"], J["phase"] = J["i"] + 1, "start"
            continue
        if J["phase"] == "start":
            if o["bid"] < J["floor"]:
                J["i"] += 1
                continue
            J["ref"] = o["bid"]
            J["walk"] = max(J["floor"], up(o["bid"] * SS["walk"], SS["tick"]))
            J["rounds"] = SS["retries"] + 1 if J["i"] == 0 else 1
            J["phase"], J["t_end"] = "sweep", ts
            if J["i"] == 0 and o["ask"] > o["bid"]:
                mid = up((o["bid"] + o["ask"]) / 2, SS["tick"])
                if mid > o["bid"]:
                    J["mid"], J["phase"], J["t_end"] = mid, "polite", ts + SS["polite_s"]
                    ex.offer_start(J, o)
        if J["phase"] == "polite":
            ex.offer_poll(J, o)
            if J["left"] > 0 and ts < J["t_end"]:
                return False
            ex.offer_stop(J, o)
            J["phase"] = "sweep"
        if J["phase"] == "sweep":
            if ts < J["t_end"]:
                return False
            if J["left"] > 0:
                ex.sweep(J, o)
            J["rounds"] -= 1
            if J["left"] > 0 and J["rounds"] > 0 and ts - J["t0"] < SS["max_job_s"] - SS["retry_wait_s"]:
                J["t_end"] = ts + SS["retry_wait_s"]
                return False
            J["i"], J["phase"] = J["i"] + 1, "start"
    J["done"] = True
    return True

def add_fill(J, o, q, price, fee=None):
    if q > 0:
        J["fills"].append(dict(sym=o["sym"], strike=o["strike"], c=int(q), price=float(price), fee=fee,
                               ref=J["ref"], walk=J["walk"]))
        J["left"] -= int(q)

class PaperExec:
    """strict paper: polite fills only when a real bid reaches our price; sweeps take real bid levels >= walk-away,
    minus what this owner already took there in the last few minutes."""
    def __init__(self, book=None):
        self.book = book or public_book
        self.used = {}

    def _take(self, J, o, levels):
        now = time.time()
        for kk in [kk for kk, v in self.used.items() if now - v[1] > SS["retry_wait_s"] + 60]:
            self.used.pop(kk)
        for p, s in levels:
            if J["left"] <= 0:
                break
            u = self.used.get((o["sym"], p), [0, now])
            q = min(J["left"], int(s) - u[0])
            if q > 0:
                add_fill(J, o, q, p)
                self.used[(o["sym"], p)] = [u[0] + q, now]

    def offer_start(self, J, o):
        pass

    def offer_poll(self, J, o):
        bids, _ = self.book(o["sym"])
        self._take(J, o, [(J["mid"], s) for p, s in bids if p >= J["mid"] - 1e-9])

    def offer_stop(self, J, o):
        pass

    def sweep(self, J, o):
        bids, _ = self.book(o["sym"])
        self._take(J, o, [(p, s) for p, s in bids if p >= J["walk"] - 1e-9])

    # buys (closing a short call): pay the real asks up to cap x ask
    def buy(self, o, n, cap_mult=1.5):
        _, asks = self.book(o["sym"])
        if not asks:
            px = o.get("ask") or (o.get("mark", 0) * 1.1)
            return [(n, px, None)] if px else []
        lim = asks[0][0] * cap_mult
        out, left = [], n
        for p, s in asks:
            if left <= 0 or p > lim + 1e-9:
                break
            q = min(left, int(s))
            out.append((q, p, None))
            left -= q
        if left > 0:  # thin paper book: assume the rest at the cap (pessimistic)
            out.append((left, lim, None))
        return out

class LiveExec:
    """real orders. client = liveorders.Live(acct). check(sym, side, contracts, reduce_only) raises to block."""
    def __init__(self, client, check, sleep=time.sleep):
        self.cl, self.check, self.sleep = client, check, sleep

    def _wait(self, oid, n, secs):
        t_end = time.time() + secs
        o = self.cl.order(oid)
        while o["filled"] < n and o["state"] not in ("cancelled", "rejected", "closed") and time.time() < t_end:
            self.sleep(1)
            o = self.cl.order(oid)
        if o["filled"] < n and o["state"] not in ("cancelled", "rejected", "closed"):
            try:
                self.cl.cancel(oid, self._sym)
            except Exception:
                pass
            o = self.cl.order(oid)
        return o

    def offer_start(self, J, o):
        self.check(o["sym"], "sell", J["left"], False)
        r = self.cl.place(o["sym"], "sell", J["left"], J["mid"], False, "ss%d" % (int(time.time() * 10) % 10 ** 9))
        J["oid"], J["ofilled"] = r["id"], 0

    def offer_poll(self, J, o):
        if not J.get("oid"):
            return
        r = self.cl.order(J["oid"])
        new = r["filled"] - J["ofilled"]
        if new > 0:
            add_fill(J, o, new, r["avg"] or J["mid"], r["fee"])
            J["ofilled"] = r["filled"]

    def offer_stop(self, J, o):
        if not J.get("oid"):
            return
        try:
            self.cl.cancel(J["oid"], o["sym"])
        except Exception:
            pass
        self.offer_poll(J, o)
        J["oid"] = None

    def _book(self, sym):
        try:
            r = self.cl._http("GET", "/v2/l2orderbook/%s" % sym, {"depth": 20})["result"]
            return (sorted([(float(x["price"]), int(x["size"])) for x in (r.get("buy") or [])], key=lambda x: -x[0]),
                    sorted([(float(x["price"]), int(x["size"])) for x in (r.get("sell") or [])], key=lambda x: x[0]))
        except Exception:
            t = self.cl.ticker(sym)
            return ([(t["bid"], 10 ** 6)] if t["bid"] > 0 else []), ([(t["ask"], 10 ** 6)] if t["ask"] > 0 else [])

    def sweep(self, J, o):
        bids, _ = self._book(o["sym"])
        lv = [x for x in bids if x[0] >= J["walk"] - 1e-9]
        if not lv:
            return
        q = min(J["left"], sum(s for _, s in lv))
        self.check(o["sym"], "sell", q, False)
        self._sym = o["sym"]
        r = self.cl.place(o["sym"], "sell", q, lv[-1][0], False, "sw%d" % (int(time.time() * 10) % 10 ** 9))
        r = self._wait(r["id"], q, SS["fill_wait_s"])
        if r["filled"]:
            add_fill(J, o, r["filled"], r["avg"], r["fee"])

    def buy(self, o, n, cap_mult=1.5):
        """reduce-only buy to close a short call: limit at cap x ask, take what is there, cancel the rest."""
        t = self.cl.ticker(o["sym"])
        if t["ask"] <= 0:
            return []
        lim = math.floor(t["ask"] * cap_mult / (t["tick"] or 0.5) + 1e-9) * (t["tick"] or 0.5)
        self._sym = o["sym"]
        r = self.cl.place(o["sym"], "buy", int(n), lim, True, "bb%d" % (int(time.time() * 10) % 10 ** 9))
        r = self._wait(r["id"], n, SS["fill_wait_s"])
        return [(r["filled"], r["avg"], r["fee"])] if r["filled"] else []
