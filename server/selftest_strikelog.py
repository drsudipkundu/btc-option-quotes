"""offline self-test of strikelog.py (no network): first sight, no change, strikes added, strikes removed, new expiry appears, bad reply."""
import os, sys, tempfile, csv, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strikelog as S
tmp = tempfile.mkdtemp()
L = S.Log(tmp)
def tk(exp, put_ks, call_ks, spot=60000.0):
    out = []
    for k in put_ks:
        out.append({"symbol": "P-BTC-%d-%s" % (k, exp), "spot_price": str(spot), "quotes": {"best_bid": "10", "best_ask": "12", "bid_size": "100", "ask_size": "200"}})
    for k in call_ks:
        out.append({"symbol": "C-BTC-%d-%s" % (k, exp), "spot_price": str(spot), "quotes": {"best_bid": "9", "best_ask": "11", "bid_size": "50", "ask_size": "60"}})
    return out
now = dt.datetime(2026, 11, 25, 1, 0, tzinfo=dt.timezone.utc)
def rows(name):
    p = os.path.join(tmp, name)
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []
n = L.step(tk("251126", [57200, 57600, 58000], [62000, 62400]), now)
ev = rows("strikelog_events.csv"); ed = rows("strikelog_edge.csv")
assert len(ev) == 1 and ev[0]["event"] == "FIRST_SEEN" and len(ed) == 1 and ed[0]["put_low"] == "57200.0", (ev, ed)
assert abs(float(ed[0]["put_low_pct"]) - 4.67) < 0.01, ed[0]
print("OK 1 first sight logged, edge row 4.67 % below spot")
L.step(tk("251126", [57200, 57600, 58000], [62000, 62400]), now)
assert len(rows("strikelog_events.csv")) == 1 and len(rows("strikelog_edge.csv")) == 1
print("OK 2 no change -> no new event, edge row not repeated inside 60 s")
L.step(tk("251126", [56400, 56800, 57200, 57600, 58000], [62000, 62400]), now)
ev = rows("strikelog_events.csv")
assert len(ev) == 2 and ev[1]["event"] == "CHANGED" and "P56400" in ev[1]["added"] and ev[1]["removed"] == "" and ev[1]["put_low"] == "56400.0", ev
print("OK 3 strikes added -> CHANGED row names them")
L.step(tk("251126", [56800, 57200, 57600, 58000], [62000, 62400]), now)
ev = rows("strikelog_events.csv")
assert len(ev) == 3 and ev[2]["removed"] == "P56400" and ev[2]["added"] == "", ev
print("OK 4 strike removed -> CHANGED row names it")
L.step(tk("251126", [56800, 57200], [62000]) + tk("261126", [57000], [63000]), now)
ev = rows("strikelog_events.csv")
assert any(e["event"] == "FIRST_SEEN" and e["expiry"] == "261126" for e in ev), ev
print("OK 5 new expiry appears -> FIRST_SEEN row")
before = len(rows("strikelog_events.csv"))
assert L.step([], now) == 0 and L.step([{"symbol": "junk"}], now) == 0 and len(rows("strikelog_events.csv")) == before
print("OK 6 empty or junk reply -> nothing written, no crash")
print("ALL 6 PASSED")
