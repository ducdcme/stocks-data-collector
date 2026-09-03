# Changelog

## 0.2.8

- Make missing-symbol catalog lookup holiday-safe when SSI `Securities` has no data.
- Vnstock fallback no longer requires `equity.list()` to contain an exchange field; it resolves HOSE/HNX/UPCOM through dedicated exchange/group membership endpoints.
- Preserve normal fast-path behavior when Vnstock already supplies valid exchange metadata.

## 0.2.7

- Make SSI stock-universe discovery holiday-safe when `Securities` or `IndexComponents` returns `There is no data`.
- Prefer last-known-good SSI group cache; otherwise fall back exchange groups to active PostgreSQL instruments without inventing VN30 membership.


## v0.2.6

- Fixed SSI `DailyStockPrice` empty-window handling during automatic corporate-action checks.
- `message = "There is no data"` is now treated as an empty factor chunk only for the `DailyStockPrice` caller.
- Other SSI endpoints retain fail-fast behavior for non-success empty responses.
- Added regression coverage for BMP-style no-data windows and endpoint isolation.

## v0.2.5

- Added automatic SSI corporate-action detection to Daily Sync.
- Added idempotent historical SSI DailyOhlc reconciliation after verified factor transitions.
- Added `corporate_action_events` migration/state to avoid repeated processing.
- Added manual corporate-action recovery and event-inspection commands.
- Kept SSI as primary/canonical adjusted OHLC source and VnStock as fallback/diagnostic.
- Updated VPS deployment to GitHub tag-based workflow.

## v0.2.4

- DB-first freshness and state-decision hardening.
- Existing current symbols skip provider calls; stale symbols sync only the missing newer edge; empty symbols bootstrap history.
