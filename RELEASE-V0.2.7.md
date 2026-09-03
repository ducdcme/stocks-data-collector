# Stocks Data Collector v0.2.7

## Fixed

- Stock universe discovery no longer fails the whole `/universe/groups` request when SSI returns `There is no data` during Vietnamese market holidays/non-trading periods.
- Uses the last successful in-memory SSI group cache when available, even after its normal TTL has expired.
- Without a previous SSI cache, HOSE/HNX/UPCOM fall back to active instruments already prepared in PostgreSQL.
- VN30 is never reconstructed from HOSE membership; without SSI/cache it returns an empty fallback group instead of inventing constituents or returning HTTP 502.
- Keeps the v0.2.6 `DailyStockPrice: There is no data` corporate-action fix.

## Validation

- Full test suite: 73 passed.
- No database migration, `.env`, or dependency changes required.
