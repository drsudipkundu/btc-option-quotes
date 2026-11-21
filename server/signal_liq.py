#!/usr/bin/env python3
"""Liquidation recorder: keeps a live connection to Binance and Bybit public liquidation streams
and appends each liquidation to liquidations.csv. Run as a service (auto-restarts).
Needs: pip install websockets   Output folder: SIGNAL_DIR or ~/deltabot/logs/signal
"""
import asyncio, csv, json, os, time
import websockets

OUT = os.environ.get("SIGNAL_DIR", os.path.expanduser("~/deltabot/logs/signal"))
os.makedirs(OUT, exist_ok=True)
PATH = os.path.join(OUT, "liquidations.csv")
HEADER = ["ts_ms", "exchange", "side_of_order", "price", "qty_btc", "usd"]

def write(row):
    first = not os.path.exists(PATH)
    with open(PATH, "a", newline="") as f:
        w = csv.writer(f)
        if first:
            w.writerow(HEADER)
        w.writerow(row)

def parse_binance(msg):
    o = msg.get("o")
    if not o or o.get("s") != "BTCUSDT":
        return None
    p, q = float(o["ap"] or o["p"]), float(o["z"] or o["q"])
    # side S=SELL means a LONG was liquidated; BUY means a SHORT was liquidated
    return [o["T"], "binance", o["S"], p, q, round(p * q, 2)]

def parse_bybit(msg):
    if not str(msg.get("topic", "")).startswith("allLiquidation"):
        return None
    out = []
    for x in msg.get("data", []):
        if x.get("s") != "BTCUSDT":
            continue
        p, q = float(x["p"]), float(x["v"])
        # Bybit S=Buy means a LONG position was liquidated (closed by a sell... reported as Buy side of position)
        out.append([x["T"], "bybit", x["S"], p, q, round(p * q, 2)])
    return out

async def binance():
    while True:
        try:
            async with websockets.connect("wss://fstream.binance.com/ws/btcusdt@forceOrder", ping_interval=20) as ws:
                async for m in ws:
                    r = parse_binance(json.loads(m))
                    if r:
                        write(r)
        except Exception as e:
            print("binance ws error", e, flush=True)
            await asyncio.sleep(5)

async def bybit():
    while True:
        try:
            async with websockets.connect("wss://stream.bybit.com/v5/public/linear", ping_interval=20) as ws:
                await ws.send(json.dumps({"op": "subscribe", "args": ["allLiquidation.BTCUSDT"]}))
                async for m in ws:
                    for r in parse_bybit(json.loads(m)) or []:
                        write(r)
        except Exception as e:
            print("bybit ws error", e, flush=True)
            await asyncio.sleep(5)

async def main():
    await asyncio.gather(binance(), bybit())

if __name__ == "__main__":
    asyncio.run(main())
