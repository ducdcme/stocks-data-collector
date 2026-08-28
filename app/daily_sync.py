from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable, Any
from zoneinfo import ZoneInfo

from .backfill import _range_limit
from .config import settings
from .corporate_action import (
    build_factor_segments,
    build_reconciliation_plan,
    detect_factor_transitions,
)
from .repository import (
    apply_corporate_action_reconciliation,
    candle_coverage,
    get_active_instruments,
    get_instrument_candles_with_provider,
    mark_sync_error,
    mark_sync_success,
    processed_corporate_action_dates,
    upsert_daily_candles,
)
from .service import StockDataService

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_CLOSE_CUTOFF = time(15, 15)


@dataclass
class CorporateActionDailyResult:
    enabled: bool
    checked: bool = False
    detection_start: str | None = None
    detection_end: str | None = None
    detected_events: list[str] = field(default_factory=list)
    new_events: list[str] = field(default_factory=list)
    already_processed_events: list[str] = field(default_factory=list)
    updated: int = 0
    inserted: int = 0
    events_recorded: int = 0
    status: str = "disabled"


@dataclass
class DailySyncResult:
    symbol: str
    provider: str
    start: str | None
    end: str
    fetched: int
    inserted: int
    updated: int
    skipped: bool = False
    reason: str | None = None
    corporate_action: CorporateActionDailyResult | None = None


def completed_market_date(now: datetime | None = None, cutoff: time = DEFAULT_CLOSE_CUTOFF) -> date:
    """Latest calendar date that is safe to request as a completed VN D1 candle.

    Holidays/weekends are intentionally not guessed here; the provider simply
    returns no candle for non-trading dates. Before the configured close cutoff
    we stop at yesterday so an intraday/partial D1 bar cannot enter PostgreSQL.
    """
    current = now.astimezone(VN_TZ) if now else datetime.now(VN_TZ)
    candidate = current.date() - timedelta(days=1) if current.time().replace(tzinfo=None) < cutoff else current.date()
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _ssi_provider(service: StockDataService):
    for provider in getattr(service, "providers", []):
        if getattr(provider, "name", "") == "ssi" and hasattr(provider, "daily_adjustment_factors"):
            return provider
    return None


def _auto_corporate_action_reconciliation(
    service: StockDataService,
    instrument: dict[str, Any],
    target: date,
    database_url: str | None,
    progress: Callable[[str], None] | None,
    lookback_days: int,
    factor_tolerance: float,
    price_tolerance: float,
) -> CorporateActionDailyResult:
    """Detect new SSI factor transitions and reconcile adjusted history once.

    Detection is intentionally independent from the daily newer-edge sync. This
    means a DB that is already current still checks for historical back-adjustment.
    A processed event is persisted only in the same transaction that reconciles
    (or confirms) SSI DailyOhlc, so subsequent daily jobs skip that event.
    """
    if lookback_days < 2:
        raise ValueError("corporate-action lookback_days must be >= 2")

    ssi = _ssi_provider(service)
    if ssi is None:
        return CorporateActionDailyResult(enabled=True, status="ssi_unavailable")

    detect_end = target
    detect_start = target - timedelta(days=lookback_days - 1)
    result = CorporateActionDailyResult(
        enabled=True,
        checked=True,
        detection_start=detect_start.isoformat(),
        detection_end=detect_end.isoformat(),
        status="checked_no_event",
    )

    factors = ssi.daily_adjustment_factors(
        instrument["symbol"],
        instrument["exchange"],
        detect_start.isoformat(),
        detect_end.isoformat(),
    )
    segments = build_factor_segments(factors, factor_tolerance)
    transitions = [
        row
        for row in detect_factor_transitions(segments, factor_tolerance)
        if row.likely_corporate_action
    ]
    result.detected_events = [row.detected_from_date for row in transitions]

    if not transitions:
        return result

    processed = processed_corporate_action_dates(
        instrument["id"],
        start=detect_start.isoformat(),
        end=detect_end.isoformat(),
        database_url=database_url,
    )
    result.already_processed_events = sorted(set(result.detected_events) & processed)
    new_transitions = [row for row in transitions if row.detected_from_date not in processed]
    result.new_events = [row.detected_from_date for row in new_transitions]

    if not new_transitions:
        result.status = "events_already_processed"
        return result

    db_rows = get_instrument_candles_with_provider(instrument["id"], database_url)
    if not db_rows:
        raise RuntimeError(f"{instrument['symbol']}: no persisted history for corporate-action reconciliation")

    history_start = db_rows[0]["date"]
    history_end = db_rows[-1]["date"]
    if progress:
        progress(
            f"{instrument['symbol']}: NEW SSI corporate action "
            f"{','.join(result.new_events)}; reconcile {history_start}..{history_end}"
        )

    ssi_rows = ssi.daily_ohlcv(
        instrument["symbol"],
        history_start,
        history_end,
        _range_limit(date.fromisoformat(history_start), date.fromisoformat(history_end)),
    )
    plan = build_reconciliation_plan(db_rows, ssi_rows, price_tolerance)
    if not plan["safe_to_apply"]:
        raise RuntimeError(
            f"{instrument['symbol']}: corporate-action reconciliation blocked: {plan['safety']}"
        )

    event_rows = [
        {
            "event_date": row.detected_from_date,
            "previous_factor": row.previous_factor,
            "new_factor": row.new_factor,
            "ratio_change_pct": row.ratio_change_pct,
            "source": "ssi",
        }
        for row in new_transitions
    ]
    counts = apply_corporate_action_reconciliation(
        instrument_id=instrument["id"],
        updates=plan["updates"],
        inserts=plan["inserts"],
        provider="ssi",
        database_url=database_url,
        processed_events=event_rows,
    )
    result.updated = counts["updated"]
    result.inserted = counts["inserted"]
    result.events_recorded = counts.get("events_recorded", len(event_rows))
    result.status = "reconciled" if (result.updated or result.inserted) else "verified_already_in_sync"

    if progress:
        progress(
            f"{instrument['symbol']}: corporate action complete events={','.join(result.new_events)} "
            f"updated={result.updated} inserted={result.inserted} recorded={result.events_recorded}"
        )
    return result


def sync_daily(
    service: StockDataService,
    symbols: list[str] | None = None,
    as_of: date | None = None,
    database_url: str | None = None,
    progress: Callable[[str], None] | None = None,
    bootstrap_days: int = 14,
    corporate_action_auto: bool | None = None,
    corporate_action_lookback_days: int | None = None,
    corporate_action_factor_tolerance: float | None = None,
    corporate_action_price_tolerance: float | None = None,
) -> list[DailySyncResult]:
    """Sync completed D1 edge and automatically repair new SSI adjustments.

    Normal daily sync remains DB-first. Corporate-action detection is a separate
    post-step and therefore also runs when the newer edge is already current.
    """
    if bootstrap_days < 1:
        raise ValueError("bootstrap_days must be >= 1")

    ca_enabled = settings.corporate_action_auto if corporate_action_auto is None else corporate_action_auto
    ca_lookback = (
        settings.corporate_action_lookback_days
        if corporate_action_lookback_days is None
        else corporate_action_lookback_days
    )
    ca_factor_tolerance = (
        settings.corporate_action_factor_tolerance
        if corporate_action_factor_tolerance is None
        else corporate_action_factor_tolerance
    )
    ca_price_tolerance = (
        settings.corporate_action_price_tolerance
        if corporate_action_price_tolerance is None
        else corporate_action_price_tolerance
    )
    if ca_enabled and ca_lookback < 2:
        raise ValueError("corporate_action_lookback_days must be >= 2")

    target = as_of or completed_market_date()
    instruments = get_active_instruments(symbols, database_url)
    results: list[DailySyncResult] = []
    total = len(instruments)

    for index, instrument in enumerate(instruments, start=1):
        symbol = instrument["symbol"]
        coverage = candle_coverage(instrument["id"], database_url)
        last = coverage.get("last_date")
        if isinstance(last, str):
            last = date.fromisoformat(last)

        result: DailySyncResult
        try:
            if last is not None and last >= target:
                reason = f"DB already current through {last}"
                if progress:
                    progress(f"[{index}/{total}] {symbol}: SKIP edge - {reason}")
                result = DailySyncResult(
                    symbol=symbol,
                    provider=instrument.get("provider") or "db",
                    start=None,
                    end=target.isoformat(),
                    fetched=0,
                    inserted=0,
                    updated=0,
                    skipped=True,
                    reason=reason,
                )
            else:
                fetch_start = last if last else (target - timedelta(days=bootstrap_days - 1))
                if fetch_start > target:
                    result = DailySyncResult(
                        symbol=symbol,
                        provider=instrument.get("provider") or "db",
                        start=None,
                        end=target.isoformat(),
                        fetched=0,
                        inserted=0,
                        updated=0,
                        skipped=True,
                        reason="No completed date to sync",
                    )
                else:
                    if progress:
                        progress(f"[{index}/{total}] {symbol}: sync {fetch_start}..{target}")

                    provider_result = service.daily_ohlcv(
                        symbol,
                        start=fetch_start.isoformat(),
                        end=target.isoformat(),
                        limit=_range_limit(fetch_start, target),
                        empty_ok=True,
                    )
                    candles = provider_result.candles
                    if last is not None:
                        candles = [row for row in candles if date.fromisoformat(row["date"]) > last]
                    counts = upsert_daily_candles(
                        instrument_id=instrument["id"],
                        candles=candles,
                        provider=provider_result.provider,
                        database_url=database_url,
                    )
                    newest = candles[-1]["date"] if candles else (last.isoformat() if last else None)
                    mark_sync_success(instrument["id"], newest, database_url)
                    result = DailySyncResult(
                        symbol=symbol,
                        provider=provider_result.provider,
                        start=fetch_start.isoformat(),
                        end=target.isoformat(),
                        fetched=len(candles),
                        inserted=counts["inserted"],
                        updated=counts["updated"],
                        skipped=False,
                        reason="no trading candle in requested range" if not candles else None,
                    )
                    if progress:
                        progress(
                            f"[{index}/{total}] {symbol}: edge complete fetched={result.fetched} "
                            f"inserted={result.inserted} updated={result.updated}"
                        )

            if ca_enabled:
                result.corporate_action = _auto_corporate_action_reconciliation(
                    service=service,
                    instrument=instrument,
                    target=target,
                    database_url=database_url,
                    progress=progress,
                    lookback_days=ca_lookback,
                    factor_tolerance=ca_factor_tolerance,
                    price_tolerance=ca_price_tolerance,
                )
            else:
                result.corporate_action = CorporateActionDailyResult(enabled=False, status="disabled")

            results.append(result)
        except Exception as exc:
            mark_sync_error(instrument["id"], str(exc), database_url)
            raise RuntimeError(f"Daily sync failed for {symbol}: {exc}") from exc

    return results
