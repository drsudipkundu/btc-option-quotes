"""Smart Sell (1-Nov-2026) for PAPER option sales - the same rules as the live night seller (nightlive.py):
  1) polite offer at the mid for 60 s (first strike only),
  2) then sell into the real bids down to the walk-away price = 80% of the bid at the start (never below the $ floor),
  3) wait 3 min and retry (3 retries on the first strike),
  4) up to 4 strikes further out (one sweep each, same 80% rule), 5) stop, keep what is sold, skip the rest.
Paper fill model (strict, never better than real life): uses Delta's LIVE order book.
  - polite offer: filled only when a real bid reaches our price (size limited to the bids at/above it);
  - sweep: fills at the real bid levels >= walk-away price, up to their real size.
Non-blocking: a sale is a job advanced every tick by ss_tick(); the strategy loop is never held up.
Use: class X(SmartSellPaper, Night) and call obj.ss_tick(now, spot, ch) every tick before obj.step(...)."""
import math, time
from nightlogic import Night, find, is_full, fee, MIN_BID

C = 0.001  # BTC per contract
SS = dict(walk=0.8, polite_s=60, retries=3, retry_wait_s=180, further=4, max_job_s=1800, tick=0.5)
_BOOK = {}

def book(sym, ttl=3.0):
    """(bids desc, asks asc) as [(price, contracts)], cached a few seconds (many paper copies share one book)."""
    hit = _BOOK.get(sym)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    import delta_api as d
    r = d.public("/v2/l2orderbook/%s" % sym, {"depth": 20})["result"]
    bids = sorted([(float(x["price"]), int(x["size"])) for x in (r.get("buy") or [])], key=lambda x: -x[0])
    asks = sorted([(float(x["price"]), int(x["size"])) for x in (r.get("sell") or [])], key=lambda x: x[0])
    _BOOK[sym] = (time.time(), (bids, asks))
    return bids, asks

def up(p, tick):
    return round(math.ceil(p / tick - 1e-9) * tick, 8)

class SmartSellPaper:
    """Mixin for Night-style paper strategies: every SELL goes through Smart Sell; buys are unchanged."""
    ss_book = staticmethod(book)

    def _ss_floor(self):
        P = getattr(self, "P", None)
        return float(P.get("min_bid", MIN_BID)) if isinstance(P, dict) else MIN_BID

    def _ss_state(self):
        st = self.S.get("ss")
        if not st or st.get("night") != self.S.get("night"):
            st = self.S["ss"] = dict(night=self.S.get("night"), jobs={}, done=[])
        return st

    def ss_pending(self):
        st = self.S.get("ss") or {}
        return bool(st.get("jobs")) and st.get("night") == self.S.get("night")

    def _ss_cands(self, o0, side):
        ch = getattr(self, "_ss_ch", None) or []
        same = [o for o in ch if o["typ"] == side and o["exp"] == o0["exp"] and not is_full(o, self.S.get("full", []))]
        if side == "CE":
            out = sorted([o for o in same if o["strike"] > o0["strike"]], key=lambda o: o["strike"])
        else:
            out = sorted([o for o in same if o["strike"] < o0["strike"]], key=lambda o: -o["strike"])
        return [o0["strike"]] + [o["strike"] for o in out[:SS["further"]]]

    # ---- Night hook: a SELL starts a job instead of filling at the bid
    def _open(self, now, spot, key, kind, side, o, qty, direction, ex_note=""):
        if direction != "S":
            return super()._open(now, spot, key, kind, side, o, qty, direction, ex_note)
        st = self._ss_state()
        if key in st["done"] or key in st["jobs"]:
            return None
        want = int(round(qty / C))
        if want <= 0:
            return None
        st["jobs"][key] = dict(key=key, kind=kind, side=side, exp=o["exp"], want=want, left=want, fills=[],
                               cands=self._ss_cands(o, side), i=0, phase="start", t0=now.timestamp(),
                               t_end=0, rounds=0, ref=0, walk=0, mid=0, note=ex_note)
        self.save()
        return self._ss_run(now, spot, key)

    def ss_tick(self, now, spot, ch):
        """advance every open Smart Sell job; call each tick (also outside the entry window)."""
        self._ss_ch = ch
        st = self.S.get("ss") or {}
        if not st.get("jobs") or st.get("night") != self.S.get("night"):
            return False
        for key in list(st["jobs"]):
            try:
                self._ss_run(now, spot, key)
            except Exception as e:
                self.log("%s smart sell %s error: %s" % (self.lab, key, e))
        self.save()
        return True

    def _ss_run(self, now, spot, key):
        st = self._ss_state()
        J = st["jobs"].get(key)
        if not J:
            return None
        ts, floor = now.timestamp(), self._ss_floor()
        ch = getattr(self, "_ss_ch", None) or []
        while J["left"] > 0 and J["i"] < len(J["cands"]):
            if ts - J["t0"] > SS["max_job_s"]:
                break
            k = J["cands"][J["i"]]
            o = find([c for c in ch if c["exp"] == J["exp"]], J["side"], k)
            if not o:
                J["i"], J["phase"] = J["i"] + 1, "start"
                continue
            if J["phase"] == "start":
                if o["bid"] < floor:
                    J["i"] += 1
                    continue
                J["ref"] = o["bid"]
                J["walk"] = max(floor, up(o["bid"] * SS["walk"], SS["tick"]))
                J["rounds"] = SS["retries"] + 1 if J["i"] == 0 else 1
                J["phase"] = "sweep"
                J["t_end"] = ts
                if J["i"] == 0 and o["ask"] > o["bid"]:
                    mid = up((o["bid"] + o["ask"]) / 2, SS["tick"])
                    if mid > o["bid"]:
                        J["mid"], J["phase"], J["t_end"] = mid, "polite", ts + SS["polite_s"]
            if J["phase"] == "polite":
                bids, _ = self.ss_book(o["sym"])
                self._ss_take(J, o, [(J["mid"], s) for p, s in bids if p >= J["mid"] - 1e-9])
                if J["left"] > 0 and ts < J["t_end"]:
                    return None
                J["phase"] = "sweep"
            if J["phase"] == "sweep":
                if ts < J["t_end"]:
                    return None
                bids, _ = self.ss_book(o["sym"])
                self._ss_take(J, o, [(p, s) for p, s in bids if p >= J["walk"] - 1e-9])
                J["rounds"] -= 1
                if J["left"] > 0 and J["rounds"] > 0 and ts - J["t0"] < SS["max_job_s"] - SS["retry_wait_s"]:
                    J["t_end"] = ts + SS["retry_wait_s"]
                    return None
                J["i"], J["phase"] = J["i"] + 1, "start"
        return self._ss_finish(now, spot, key)

    def _ss_take(self, J, o, levels):
        """fill against real bid levels, minus what THIS copy already took there in the last few minutes
        (our own earlier fills would have used up those bids in real life)."""
        now = time.time()
        used = self.__dict__.setdefault("_ss_used", {})
        for kk in [kk for kk, v in used.items() if now - v[1] > SS["retry_wait_s"] + 60]:
            used.pop(kk)
        for p, s in levels:
            if J["left"] <= 0:
                break
            u = used.get((o["sym"], p), [0, now])
            q = min(J["left"], int(s) - u[0])
            if q > 0:
                J["fills"].append([o["sym"], o["strike"], q, p, J["ref"], J["walk"]])
                J["left"] -= q
                used[(o["sym"], p)] = [u[0] + q, now]

    def _ss_finish(self, now, spot, key):
        st = self._ss_state()
        J = st["jobs"].pop(key)
        st["done"].append(key)
        first = None
        by = {}
        for sym, k, q, p, ref, walk in J["fills"]:
            a = by.setdefault(sym, [k, 0, 0.0, ref, walk])
            a[1] += q
            a[2] += q * p
        for sym, (k, q, val, ref, walk) in by.items():
            avg, qty = val / q, round(q * C, 3)
            leg = dict(id=self.S["next_id"], set=key, kind=J["kind"], side=J["side"], sym=sym, strike=k, qty=qty,
                       dir="S", entry=avg, t=now.isoformat(), closed=False, exit=None, fee=fee(spot, avg, qty))
            self.S["next_id"] += 1
            self.S["legs"].append(leg)
            self.row(now, "SELL", leg, avg, leg["fee"], 0.0, "smart sell paper; start bid %.1f walk-away %.1f%s" % (
                ref, walk, ("; " + J["note"]) if J["note"] else ""))
            self.notify("%s SOLD %s %.3f BTC @ %.1f (smart sell)" % (self.lab, sym, qty, avg), "set=%s kind=%s spot=%.1f" % (key, J["kind"], spot))
            first = first or leg
        if J["left"] > 0:
            self.row(now, "SKIP", None, 0, 0, 0, "%s: sold %d of %d contracts, rest skipped (walk-away price / thin book; %d strike(s) tried)" % (
                key, J["want"] - J["left"], J["want"], min(J["i"] + 1, len(J["cands"]))))
        if first and key not in self.S["fired"]:
            self.S["fired"].append(key)
        self.save()
        return first


class SmartNight(SmartSellPaper, Night):
    """the server's paper night copies (v4A-CG, v5A-CG, v4A-CG-SL, v5A-CG-SL) with Smart Sell"""
    pass
