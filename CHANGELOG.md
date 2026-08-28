# Changelog

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
