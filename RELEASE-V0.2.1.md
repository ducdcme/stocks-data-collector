# Stocks Data Collector v0.2.1

Maintenance release after the first Trading Signal v3.3.0 production backfill.

## Fixed

- Retry transient SSI TLS/read/connect failures before provider fallback.
- Reuse one SSI `httpx.Client` connection pool to reduce repeated TLS handshakes during bulk imports.
- Cache SSI Securities catalogue for 5 minutes by default.
- Failed/incomplete backfill now deactivates the instrument while preserving downloaded candles. Re-importing the same symbol/list automatically retries Smart Backfill.
- Add failure log now includes the symbol, candle count and reason.

## Compatibility

- No database migration.
- No Trading Signal API change.
- Existing PostgreSQL history is preserved.
- Compatible with Trading Signal v3.3.0.

## Regression

- `43 passed`
- `python -m compileall app scripts tests` PASS
