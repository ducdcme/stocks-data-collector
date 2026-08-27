# Stocks Data Collector v0.2.2

Maintenance release for production Stock bootstrap/readiness behavior.

## Fixes

- DB-first `/admin/instruments`: existing symbols are checked in PostgreSQL before any SSI/Vnstock catalog or candle request.
- Existing symbols with at least 100 D1 candles are treated as signal-ready and returned immediately with zero provider calls. Daily Sync remains responsible for freshness.
- `active` now represents whether a symbol is managed/visible, not whether a 3-year bootstrap is complete.
- Symbols with 1..99 candles remain active and chartable. They may not have enough history for all indicators/signals, but they are never hidden merely for having short history.
- Backfill/provider failures no longer deactivate instruments. Existing candles are preserved and remain visible.
- Re-adding an instrument that was previously deactivated reactivates it first; if it already has >=100 candles, provider calls are skipped.
- Three-year backfill remains a best-effort bootstrap target, not a readiness requirement.

## Production policy

- Chart visibility: >= 1 persisted D1 candle.
- Signal readiness target: >= 100 persisted D1 candles.
- Bootstrap target: up to 3 years when source history is available.
- Freshness: handled by Daily Sync, not repeated bulk-add requests.

## Database

No schema migration is required from v0.2.1.

> Superseded by v0.2.3. Do not deploy v0.2.2 to production; its prepare endpoint incorrectly used the 100-candle signal threshold as a provider-skip condition.
