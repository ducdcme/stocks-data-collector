# Stocks Data Collector v0.2.8

## Holiday-safe missing-symbol preparation

This release hardens catalog lookup after long Vietnamese market holidays or other periods where upstream reference data is temporarily incomplete.

### Changes

- Keep SSI `Securities` as the primary catalog source.
- When Vnstock `Reference.equity.list()` returns a valid symbol without an exchange field, resolve HOSE/HNX/UPCOM from `list_by_exchange()`.
- If the exchange list is also incomplete/unavailable, fall back to explicit `list_by_group(HOSE/HNX/UPCOM)` membership checks.
- If the broad Vnstock symbol list itself errors with an upstream no-data response, still attempt exchange/group membership before failing the symbol.
- Preserve company name from the broad list whenever available.
- Includes the v0.2.6 DailyStockPrice no-data fix and v0.2.7 holiday-safe universe/group fallback.

### Database / configuration

- No database migration.
- No `.env` changes.
- No dependency changes.

### Tests

- Full suite: 76 passed.
- Added regression coverage for missing exchange metadata and holiday no-data fallbacks.
