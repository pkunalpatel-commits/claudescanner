# Dhan NSE F&O OI Gain Scanner (Android / Kivy)

Live OI gain/change, LTP, estimated turnover, LTP x ChgOI (and x lot size), dynamic ATM +/- N CE/PE strikes,
12 timeframes (1m-1D), thresholds per timeframe, alerts, SQLite history. Real DhanHQ v2 APIs; no mock data.

## Build the APK (GitHub)
1. Create a GitHub repo, push this folder to `main`.
2. Open **Actions -> Build APK** (runs on push, or "Run workflow"). First build takes ~25-40 min.
3. Download the `DhanOIScanner-apk` artifact, unzip, install the `.apk` on your phone (allow unknown sources).

## Use
Settings -> enter Dhan **Client ID + Access Token** (web.dhan.co -> My Profile -> DhanHQ Trading APIs; token lasts 24h;
"Renew token" works while it is valid). Live feed needs the **Data APIs** subscription. Select stocks, expiry, N, timeframes, Apply.

## Run on desktop for testing
`pip install kivy requests websocket-client certifi` then `python main.py`.

## Modules
main, dhan_auth (REST+quote, 1 req/s), dhan_market_feed (WS v2, auto-reconnect, <=100/msg, 5000/conn, 5 conns),
instrument_master (daily detailed scrip master; security IDs, expiries, strikes, lots - nothing hardcoded),
expiry_manager, atm_strike_manager, subscription_manager (diff-based, no duplicates), oi_calculation_engine,
turnover_engine, timeframe_engine (trading-time baselines), scanner_engine, alert_engine, database_manager, settings, dashboard.

## Historical scan (backfill)
On connect the app loads the previous session + today's 1-minute bars **with OI** for every monitored contract from
Dhan's `POST /v2/charts/intraday` (`oi=true`), so all timeframes (1m-1D) work immediately instead of waiting for live data to
build up. Data API limit ~5 req/s, so 100 contracts take ~30 s. Toggle/trigger it in Settings ("Backfill history now").
History turnover is an estimate (bar close x volume).

## History tab (date-wise / time-wise scan)
Choose **dates** (From/To, max 10 sessions), a **time window** (e.g. 09:15 to 10:00), a timeframe, direction, CE/PE, then **RUN**.
Modes: **Peak** = strongest OI move per contract in the range; **Date-wise** = strongest per date (one row per contract per day);
**Time-wise** = strongest per time slot of the session (15m / 30m / 1H slots) across the chosen dates.
(1D compares end-of-day vs previous end-of-day OI; the time window does not apply to 1D.)
Uses Dhan 1-minute history with OI for your selected stocks / expiry / ATM +/- N. Only currently listed contracts are available.

## Filters and sorting (Scanner, Multi-TF, History, Alerts)
- **LTP % greater-than / less-than** (e.g. `> 2` and `< 10`, or `< -3` for falling premiums) - Scanner and History.
- **Asc / Desc** toggle on every results screen; sort by OI Gain %, |OI %|, OI Change, Turnover, LTPxChgOI, LTP %, ATM distance, strike, stock.

## How it works / limitations (please read)
- **Baselines**: rolling, in *trading time* (09:15-15:30 IST; nights/weekends/holidays skipped). Intraday baselines need history:
  a timeframe shows "-" until enough snapshots exist (restored from SQLite after restart). **1D** uses Dhan's previous-close OI
  packet, else yesterday's last stored snapshot.
- **Holidays**: Dhan has no holiday API; enter NSE holidays (YYYY-MM-DD) in Settings.
- **Turnover** is *estimated* (ATP x volume, window = difference vs baseline). Dhan's feed has no trade-level data. Marked `Turn~`.
- `LTP x ChgOI` and `x lot size` are notional indicators, not traded amounts or buyer/seller values.
- Limits: 5000 instruments per WS connection, 5 connections, 100 per subscribe message, Quote REST 1 req/s. All stocks with large N
  can exceed 25k instruments -> reduce N or stocks. Memory/battery grow with contracts monitored.
- **Android background**: the OS may pause the app when minimized/screen off; the app keeps the screen on while open.
  No foreground service is included, so alerts are reliable only while the app is open.
- No pandas/numpy (heavy on Android); pure-Python calculations. Windows EXE from the original spec is not included.
- Not tested against a live Dhan account in this environment: check `scanner.log` (app data dir) if the feed shows errors.
- Scanner only: no indicators, no buy/sell signals.
