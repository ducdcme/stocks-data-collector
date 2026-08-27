# Stocks Data Collector v0.2.4

Production maintenance patch for DB-first freshness state decisions.

## Fixed

- A historical `sync_status=error` could force Smart Backfill even when PostgreSQL already contained the latest completed D1 candle.
- Re-submitting a current symbol could therefore call SSI/Vnstock unnecessarily, hit provider rate limits/timeouts, and return 502 despite complete local data.

## Final decision policy

1. New symbol or `candle_count == 0`: bootstrap/backfill.
2. Existing symbol with candles and stale `MAX(trade_date)`: Daily Sync only the missing recent edge.
3. Existing symbol with `MAX(trade_date) >= latest completed session`: return current from PostgreSQL and make zero provider data calls.
4. `sync_status` is diagnostic only.
5. `>=100 candles` is signal-readiness only.
6. Provider errors never change `is_active`.

No database migration is required. Compatible with Trading Signal v3.3.1.

Regression: 51/51 tests PASS; Python compileall PASS.
