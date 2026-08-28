# Stocks Data Collector v0.2.5

## Release goal

Keep PostgreSQL historical D1 candles aligned with SSI's current adjusted OHLC after corporate actions. SSI owns adjustment mathematics; SDC only detects verified SSI factor transitions and reconciles persisted candles with the current SSI `DailyOhlc` result.

## Changes

- SSI remains the primary/canonical source; VnStock remains fallback/diagnostic.
- Daily Sync performs corporate-action factor lookback independently from newer-edge freshness.
- A new, unprocessed SSI factor transition triggers historical reconciliation against current SSI DailyOhlc.
- Reconciliation updates only materially different OHLC rows, may insert missing SSI sessions, never deletes DB rows, and is idempotent.
- Corporate-action event state is persisted in `corporate_action_events` so the same event is not reconciled every day.
- Candle reconciliation and processed-event recording share one PostgreSQL transaction.
- Manual corporate-action recovery requires SSI verification before `--apply --force` is accepted.
- `scripts.corporate_action_events` provides read-only processed-event inspection.

## Required migration

```bash
python -m scripts.migrate
```

Applies `002_corporate_action_events.sql`.

## Real-data validation completed

- MBB event `2026-08-11`: stale local history reconciled against SSI; a second run produced zero changes.
- VIX event `2026-08-20`: stale local history reconciled against SSI; a second run produced zero changes.
- NTP events `2026-05-26` and `2026-06-10`: both transitions detected in one lookback window, recorded once, and subsequent run reported both as already processed.
- Daily edge already current does not suppress corporate-action detection.

## Regression

Release code is based on the validated v0.2.5-dev6 runtime.
