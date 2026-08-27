from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .backfill import _range_limit
from .repository import (
    candle_coverage,
    get_active_instruments,
    mark_sync_error,
    mark_sync_success,
    upsert_daily_candles,
)
from .service import StockDataService

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DEFAULT_CLOSE_CUTOFF = time(15, 15)


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


def completed_market_date(now: datetime | None = None, cutoff: time = DEFAULT_CLOSE_CUTOFF) -> date:
    """Latest calendar date that is safe to request as a completed VN D1 candle.

    Holidays/weekends are intentionally not guessed here; the provider simply
    returns no candle for non-trading dates. Before the configured close cutoff
    we stop at yesterday so an intraday/partial D1 bar cannot enter PostgreSQL.
    """
    current = now.astimezone(VN_TZ) if now else datetime.now(VN_TZ)
    candidate = current.date() - timedelta(days=1) if current.time().replace(tzinfo=None) < cutoff else current.date()
    # VN exchanges are closed on Saturday/Sunday. Public holidays remain
    # provider-verified because the collector intentionally has no hard-coded
    # holiday calendar.
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def sync_daily(
    service: StockDataService,
    symbols: list[str] | None = None,
    as_of: date | None = None,
    database_url: str | None = None,
    progress: Callable[[str], None] | None = None,
    bootstrap_days: int = 14,
) -> list[DailySyncResult]:
    """Fetch only the missing newer edge and persist completed D1 candles."""
    if bootstrap_days < 1:
        raise ValueError("bootstrap_days must be >= 1")

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

        if last is not None and last >= target:
            reason = f"DB already current through {last}"
            if progress:
                progress(f"[{index}/{total}] {symbol}: SKIP - {reason}")
            results.append(
                DailySyncResult(
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
            )
            continue

        # Include the last persisted trading day as an anchor. This avoids an
        # all-empty provider response across weekends/holidays (which some
        # Community builds can mistake for a quota/upstream failure). We filter
        # the anchor back out before UPSERT, so only genuinely new candles are
        # written.
        fetch_start = last if last else (target - timedelta(days=bootstrap_days - 1))
        if fetch_start > target:
            reason = "No completed date to sync"
            results.append(
                DailySyncResult(
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
            )
            continue

        if progress:
            progress(f"[{index}/{total}] {symbol}: sync {fetch_start}..{target}")

        try:
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
            results.append(result)
            if progress:
                progress(
                    f"[{index}/{total}] {symbol}: complete fetched={result.fetched} "
                    f"inserted={result.inserted} updated={result.updated}"
                )
        except Exception as exc:
            mark_sync_error(instrument["id"], str(exc), database_url)
            raise RuntimeError(f"Daily sync failed for {symbol}: {exc}") from exc

    return results
