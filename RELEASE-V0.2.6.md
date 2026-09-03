# Stocks Data Collector v0.2.6

## Release goal

Prevent a valid empty SSI `DailyStockPrice` window from aborting Daily Sync during automatic corporate-action detection.

## Fix

SSI may return HTTP 200 with a non-success payload such as `message = "There is no data"` when `DailyStockPrice` has no rows for a requested chunk. In v0.2.5 this response propagated as a fatal exception, causing errors such as:

```text
Daily sync failed for BMP: SSI DailyStockPrice failed: There is no data
```

v0.2.6 adds an explicit `allow_no_data` path to the internal SSI GET helper and enables it only for `daily_adjustment_factors()` / `DailyStockPrice`. Such chunks are normalized to `data = []` and corporate-action detection continues normally.

## Safety

- `DailyOhlc`, `Securities`, `IndexComponents`, and other SSI callers keep the existing fail-fast behavior.
- No database migration is required.
- Corporate-action auto reconciliation remains enabled and unchanged.
- No candle normalization or persistence logic changed.

## Regression

- Added a BMP-style `DailyStockPrice` no-data test.
- Added a guard test confirming other SSI endpoints still raise on the same error payload.
- Full test suite: 69 passed.
