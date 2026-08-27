# Stocks Data Collector v0.2.3

Production consistency patch.

## Fixed

- Restores DB freshness as the only normal reason to skip provider calls when preparing an existing symbol.
- Removes the incorrect v0.2.2 behavior where `>=100` candles alone could skip provider updates.
- Keeps `>=100` candles strictly as signal-readiness metadata.
- Existing stale symbols now use Daily Sync (newer edge only), rather than repeating full backfill/provider catalog work.
- New/empty symbols still bootstrap historical data.
- Previous failed bootstrap state retries Smart Backfill on the next prepare request.
- Provider/backfill errors never deactivate instruments or hide existing chart data.
- Weekend freshness checks resolve to the previous Friday.

## Compatibility

- No database migration required.
- API remains compatible with Trading Signal v3.3.1.
- Existing PostgreSQL data and `/etc/stocks-data-collector.env` are preserved.

## Regression

- 50/50 tests PASS.
- Python compileall PASS.
