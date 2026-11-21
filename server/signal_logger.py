#!/usr/bin/env python3
"""Signal logger: saves BTC sentiment/derivative data that free APIs only keep for ~30 days.
Run hourly from cron. Appends new rows only (no duplicates). Python 3.8+, standard library only.
Output folder: SIGNAL_DIR env var or ~/deltabot/logs/signal
Files: oi_binance.csv, ls_global_binance.csv, ls_top_binance.csv, oi_bybit.csv, ls_bybit.csv,
       funding_binance.csv, dvol_hourly.csv, fng_daily.csv
"""
import csv, json, os, sys, time, urllib.request, urllib.parse

OUT = os.environ.get("SIGNAL_DIR", os.path.expanduser("~/deltabot/logs/signal"))
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "signal-logger/1.0"}

def get(url, params=None, tries=3):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            err = e
            time.sleep(2 * (i + 1))
    print("FAIL", url, err, file=sys.stderr)
    return None

def append(name, header, rows):
    """rows: list of lists, first column is the unique key (timestamp ms). Returns count added."""
    path = os.path.join(OUT, name)
    seen = set()
    if os.path.exists(path):
        with open(path, newline="") as f:
            for r in csv.reader(f):
                if r:
                    seen.add(r[0])
    new = [r for r in rows if str(r[0]) not in seen]
    if not new:
        return 0
    new.sort(key=lambda r: int(r[0]))
    first = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if first:
            w.writerow(header)
        w.writerows(new)
    return len(new)

def binance_hist(path, name, header, fields):
    d = get("https://fapi.binance.com/futures/data/" + path,
            {"symbol": "BTCUSDT", "period": "1h", "limit": 500})
    if not isinstance(d, list):
        return
    rows = [[x["timestamp"]] + [x.get(k) for k in fields] for x in d]
    print(name, "added", append(name, header, rows))

def main():
    binance_hist("openInterestHist", "oi_binance.csv",
                 ["ts_ms", "oi_btc", "oi_usd"], ["sumOpenInterest", "sumOpenInterestValue"])
    binance_hist("globalLongShortAccountRatio", "ls_global_binance.csv",
                 ["ts_ms", "long_acct", "short_acct", "ratio"], ["longAccount", "shortAccount", "longShortRatio"])
    binance_hist("topLongShortPositionRatio", "ls_top_binance.csv",
                 ["ts_ms", "long_pos", "short_pos", "ratio"], ["longAccount", "shortAccount", "longShortRatio"])
    # Bybit
    d = get("https://api.bybit.com/v5/market/open-interest",
            {"category": "linear", "symbol": "BTCUSDT", "intervalTime": "1h", "limit": 200})
    if d and d.get("result"):
        rows = [[x["timestamp"], x["openInterest"]] for x in d["result"]["list"]]
        print("oi_bybit added", append("oi_bybit.csv", ["ts_ms", "oi_btc"], rows))
    d = get("https://api.bybit.com/v5/market/account-ratio",
            {"category": "linear", "symbol": "BTCUSDT", "period": "1h", "limit": 200})
    if d and d.get("result"):
        rows = [[x["timestamp"], x["buyRatio"], x["sellRatio"]] for x in d["result"]["list"]]
        print("ls_bybit added", append("ls_bybit.csv", ["ts_ms", "buy_ratio", "sell_ratio"], rows))
    # Funding (Binance, last 1000 settlements)
    d = get("https://fapi.binance.com/fapi/v1/fundingRate", {"symbol": "BTCUSDT", "limit": 1000})
    if isinstance(d, list):
        rows = [[x["fundingTime"], x["fundingRate"]] for x in d]
        print("funding added", append("funding_binance.csv", ["ts_ms", "rate"], rows))
    # DVOL hourly (Deribit), last ~30 days
    end = int(time.time() * 1000)
    d = get("https://www.deribit.com/api/v2/public/get_volatility_index_data",
            {"currency": "BTC", "resolution": "3600", "start_timestamp": end - 30 * 86400000, "end_timestamp": end})
    if d and d.get("result"):
        rows = [[x[0], x[1], x[2], x[3], x[4]] for x in d["result"]["data"]]
        print("dvol added", append("dvol_hourly.csv", ["ts_ms", "open", "high", "low", "close"], rows))
    # Fear & Greed daily
    d = get("https://api.alternative.me/fng/", {"limit": 10})
    if d and d.get("data"):
        rows = [[int(x["timestamp"]) * 1000, x["value"], x["value_classification"]] for x in d["data"]]
        print("fng added", append("fng_daily.csv", ["ts_ms", "value", "label"], rows))

if __name__ == "__main__":
    main()
