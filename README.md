# VN Stocks Data Collector v0.2.5

Production VN stock data service for Trading Signal v3.3.1.

## Current architecture

```text
SSI FastConnect Data (PRIMARY)
          ↓ fail
Vnstock Community (FALLBACK)
          ↓
backfill / daily sync
          ↓
PostgreSQL stocks_data
          ↓
REST API :8790
          ↓
Trading Signal v3.3.1
```

Trading Signal reads candles from PostgreSQL. SSI/Vnstock are upstream sources used by collector jobs.

## Local Windows setup with .env

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create local config once:

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill at least:

```env
STOCKS_DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/stocks_data
SSI_CONSUMER_ID=YOUR_CONSUMER_ID
SSI_CONSUMER_SECRET=YOUR_CONSUMER_SECRET
```

Provider defaults are already:

```env
STOCKS_PROVIDER_PRIMARY=ssi
STOCKS_PROVIDER_FALLBACK=vnstock
```

`.env` is ignored by Git. OS environment variables override `.env` values.

## Start API

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
```

Check:

```powershell
curl.exe http://127.0.0.1:8790/health
curl.exe http://127.0.0.1:8790/health/db
```

With SSI configured, `/health` should show:

```json
"providers": ["ssi", "vnstock"]
```

## Daily sync

All active symbols:

```powershell
python -m scripts.sync_daily
```

Selected symbols:

```powershell
python -m scripts.sync_daily --symbols FPT HPG MBB DGC VIX
```

Daily sync only fetches the missing newer edge and only stores completed VN D1 candles.

## Backfill

```powershell
python -m scripts.backfill --symbols FPT HPG MBB DGC VIX --years 3
```

Smart backfill checks PostgreSQL first and skips already-covered ranges. Force refresh is available when required:

```powershell
python -m scripts.backfill --symbols FPT --years 3 --force
```

## Dynamic stock universe

Trading Signal can add a new symbol through the collector admin API. The collector resolves metadata, activates the instrument, and smart-backfills history. Removing a symbol deactivates it while preserving candles.

## Provider behavior

Default order:

```text
SSI primary -> Vnstock fallback
```

Logs explicitly show which provider handled the request and when fallback occurs. If SSI credentials are missing, the configured Vnstock fallback can still start the service.

Vnstock Guest throttling remains enabled for fallback/backfill use.

## SSI validation tools

```powershell
python -m scripts.test_ssi --symbol FPT --days 30
python -m scripts.compare_providers --symbols FPT HPG --days 30
```

## Database migration/statistics

```powershell
python -m scripts.migrate
python -m scripts.stats --symbols FPT HPG MBB DGC VIX
```

## Tests

```powershell
python -m pytest -q
```

Release regression target: **67 tests**.

> Note: tests that intentionally exercise fake/in-memory API branches should be run in a clean test environment; a local `.env` with a real `STOCKS_DATABASE_URL` can select database-backed behavior for environment-sensitive tests.


## v0.2.1 production hardening

Bulk add/backfill is resilient to transient SSI network failures:

- SSI uses a persistent HTTP connection pool instead of creating a new TLS connection per request.
- Transient `httpx` transport/time-out errors are retried before falling back to Vnstock.
- SSI `Securities` results are cached briefly so importing many symbols does not repeatedly query the same market catalogue.
- If an instrument is created/reactivated but its backfill fails, it is deactivated again while any downloaded candles are preserved. Re-importing the same list therefore retries Smart Backfill automatically instead of treating that symbol as already prepared.

Recommended production defaults:

```env
SSI_REQUEST_RETRIES=2
SSI_RETRY_DELAY_SECONDS=1
SSI_SECURITIES_CACHE_SECONDS=300
```

## v0.2.2 readiness policy

`active` is a visibility/management flag, not a history-completeness flag. A symbol with any persisted candles remains chartable. The current signal workflow uses 100 D1 candles as its readiness target; a three-year history is only a best-effort bootstrap target. Re-importing a symbol with at least 100 candles is DB-first and makes no SSI/Vnstock candle request; Daily Sync owns freshness.

## v0.2.4 production freshness policy

v0.2.3 restores the production/dev separation between chartability, signal readiness, and freshness:

- `candle_count > 0`: the symbol remains active/chartable.
- `candle_count >= STOCKS_MIN_PREPARED_CANDLES` (default `100`): signal-readiness only.
- Provider calls are skipped only when PostgreSQL already contains D1 data through the latest completed market date at request time.
- Existing but stale symbols use Daily Sync and fetch only the newer edge.
- New/empty symbols bootstrap history (up to the configured years).
- A previous failed bootstrap (`sync_status.status=error`) retries Smart Backfill on the next prepare request.
- `is_active` is only the managed/visible flag and is never changed because of provider timeout, candle count, or signal readiness.
- Saturday/Sunday are rolled back to Friday for freshness checks. Public holidays are verified by the provider rather than hard-coded into the collector.


## v0.2.4 state-decision hardening

`/admin/instruments` now decides work exclusively from persisted candle coverage:

- `count == 0` (or a brand-new instrument) -> bootstrap/backfill history.
- `count > 0` and `MAX(trade_date) < latest completed market date` -> Daily Sync only the missing recent edge.
- `count > 0` and `MAX(trade_date) >= latest completed market date` -> DB-first current response; zero SSI/Vnstock data calls.
- historical `sync_status=error` is diagnostic only and never forces a full backfill.
- `>=100` candles remains signal readiness only; it never controls provider freshness.
- `is_active` remains management/visibility state only.

## Corporate-action auto reconciliation (v0.2.5)

SSI is the canonical adjusted OHLC source. SDC never calculates adjusted prices itself. Daily Sync now performs two independent steps per active symbol:

```text
DB-first newer-edge sync
        +
SSI factor-transition lookback
        ↓
new unprocessed corporate action?
  no  -> no historical fetch
  yes -> fetch current SSI DailyOhlc history
         diff PostgreSQL
         update/insert only changed sessions
         record processed event transactionally
```

The corporate-action check still runs when the newer edge is already current, so an SSI historical back-adjustment cannot be missed merely because PostgreSQL already has today's D1 candle. Processed events are stored in `corporate_action_events`; the same event is not reconciled again on subsequent daily jobs.

Run the required migration once after upgrading:

```bash
python -m scripts.migrate
```

Normal daily sync (auto corporate-action detection is enabled by default):

```bash
python -m scripts.sync_daily --symbols MBB VIX NTP
```

Inspect processed events:

```bash
python -m scripts.corporate_action_events --symbols MBB VIX NTP
```

Temporarily disable the automatic check for diagnostics only:

```bash
python -m scripts.sync_daily --symbols MBB --no-corporate-action
```

Manual recovery/diagnostic mode remains available. SSI must independently verify every requested event before write mode is allowed:

```bash
python -m scripts.corporate_action --symbol MBB --event-date 2026-08-11
python -m scripts.corporate_action --symbol MBB --event-date 2026-08-11 --apply --force
```

Configuration defaults:

```env
STOCKS_CORPORATE_ACTION_AUTO=true
STOCKS_CORPORATE_ACTION_LOOKBACK_DAYS=45
STOCKS_CORPORATE_ACTION_FACTOR_TOLERANCE=0.0005
STOCKS_CORPORATE_ACTION_PRICE_TOLERANCE=0.05
```

`0.05` is 50 VND because persisted stock prices use thousand-VND units.
