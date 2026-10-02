# btc-option-quotes

Snapshots of **public** BTC option and BTCUSD perpetual quotes (best bid/ask, sizes, mark price, IV,
greeks, open interest) from Delta Exchange India's public market-data API, recorded by GitHub Actions.

**What this repository contains:** only public market data that anyone can read from
`https://api.india.delta.exchange` without logging in, plus the scripts that collect it.
**It contains no API keys, no passwords, no account data, no orders and no personal information.**
The collector never logs in and cannot trade.

Purpose: Delta keeps no history of bid/ask quotes, so this archive records them going forward, to
measure the real cost of selling and buying back short-dated covered calls and buying protective puts.
Nothing is back-filled or invented; a slot that could not be captured is listed in `missing.csv`.

## Schedule (GitHub Actions, UTC cron)

| Workflow | When | What |
|---|---|---|
| `snapshots.yml` | every 30 minutes | one snapshot |
| `evening.yml` | starts 11:30 UTC (17:00 IST) | one snapshot every minute 17:08-17:47 IST, then audits yesterday's half-hour slots |
| `monthly.yml` | 2nd of each month, 03:00 UTC | merges the finished month into `parquet/YYYY-MM.parquet` and deletes its CSVs |

GitHub often starts scheduled runs a few minutes late; every row records the real time.

## Files

```
data/YYYY/MM/DD/quotes_HHMM_<tag>.csv.gz   one snapshot (UTC date and time); tag = halfhour | evening
data/YYYY/MM/DD/missing.csv                slots that were not captured, with the reason
parquet/YYYY-MM.parquet                    a finished month, all snapshots in one file
parquet/YYYY-MM_missing.csv                that month's missing slots
```

## Which contracts

Per snapshot, from the live chain: the **current and next daily** expiry (the two nearest), the
**current and next weekly** (two nearest Fridays), and the **current monthly** (nearest last-Friday
expiry), strikes from **spot -25 % to spot +15 %**, calls and puts, plus one `BTCUSD` perpetual row.
About 310 option rows per snapshot. All BTC options settle at 12:00 UTC (17:30 IST).

## Columns

| Column | Meaning |
|---|---|
| `ts_utc`, `ts_ist` | the minute this snapshot belongs to (UTC / IST) |
| `fetch_utc` | exact time the reply arrived |
| `api_ts_utc`, `quote_age_s` | Delta's own snapshot time, and how old the quote was on arrival (CDN cache, typically 3-12 s) |
| `tag` | which workflow took it |
| `symbol`, `type`, `strike` | e.g. `C-BTC-88800-031026`, `C` / `P` / `PERP` |
| `expiry_utc`, `minutes_to_expiry` | settlement time and minutes left |
| `expiry_tags` | why it was kept: `daily1`, `daily2`, `weekly1`, `weekly2`, `monthly` (can be several, joined by `|`) |
| `spot` | BTC index price |
| `best_bid`, `best_ask` | top of book in USD; **empty if that side had no order -- never filled in** |
| `bid_size`, `ask_size` | quoted size in contracts (1 contract = 0.001 BTC) |
| `mark`, `mark_iv`, `bid_iv`, `ask_iv` | Delta's mark price and implied vols (decimal, 0.45 = 45 %) |
| `delta`, `gamma`, `theta`, `vega` | Delta's greeks |
| `oi` | open interest in contracts |
| `volume_24h` | 24 h volume (empty if Delta omitted it, i.e. no trades) |
| `funding_rate` | perp row only, as Delta reports it (percent per funding interval) |
| `spread_pct_mark` | (ask - bid) / mark x 100 -- the FULL spread in percent |
| `bid_at_floor`, `ask_at_cap` | the quote sits on Delta's price-band limit = an empty book in disguise |

## Scripts

- `collector.py` -- one snapshot, or one per minute in an IST window (`--every 60 --from-ist --until-ist`)
- `publish.py` -- commits a run's files; safe when two workflows finish at once
- `audit.py` -- lists half-hour slots of a finished day that have no snapshot at all
- `merge_month.py` -- monthly CSV -> Parquet merge, verified before deleting

## The report (on the PC)

The repository is copied to Google Drive at `E:\My Drive\MarketDatabtcusd\option_quotes_repo\` by the
Windows task **BTC-Option-Quotes-Sync** (at logon and every 6 hours; log: `...tcusd\option_quotes_sync.log`).
Nothing is lost while the PC is off -- everything is on GitHub and the next sync catches up.

```
cd "E:\My Drive\MarketDatabtcusd\option_quotes_repo"
python option_quote_report.py                                  # all recorded days
python option_quote_report.py --start 2026-10-03 --end 2026-10-31 --out "E:\My Drive\MarketDatabtcusd\option_quote_reports"
```

It writes `sells_*.csv`, `roundtrip_*.csv`, `spreads_*.csv`, `puts_*.csv` and `summary_*.md`:
1. **sells** -- each day at 17:35 IST, the call expiring tomorrow nearest delta 0.03: strike, % above spot,
   bid / ask / mark, spread %. We would sell at the **bid**. If Delta did not list a strike that far out,
   the row shows the nearest delta that *was* listed -- check the `delta` column.
2. **roundtrip** -- that contract next day 17:20-17:29 IST: ask (min / median / last) = buy-back cost at the
   **ask**, and net USD per lot (0.001 BTC) after fees, fee per side = min(0.01 % of notional, 3.5 % of premium) + 18 % GST.
3. **spreads** -- median and 75th-percentile spread % of mark by |delta| bucket (0.01-0.05, 0.05-0.10, 0.10-0.30),
   hour of day (IST), call/put, daily/weekly/monthly.
4. **puts** -- monthly puts nearest delta -0.05 and -0.10 at 17:35 IST: ask, and ask as % of spot = cost of protection.

Quotes with an empty side or sitting on Delta's price-band limit are never used as a price.
Needs Python with `pandas` (and `pyarrow` once monthly Parquet files exist).

## If GitHub ever pauses the schedules

GitHub disables scheduled workflows in a public repository after 60 days without activity. The data
commits count as activity, so this should not happen. If it does: open the repository -> **Actions** tab
-> click the paused workflow in the left list -> click **Enable workflow**. Do it for each of the three.
