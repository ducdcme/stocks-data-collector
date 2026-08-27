from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from .repository import (
    candle_coverage,
    get_active_instruments,
    mark_sync_error,
    mark_sync_success,
    upsert_daily_candles,
)
from .service import StockDataService


@dataclass
class BackfillResult:
    symbol: str
    provider: str
    start: str
    end: str
    fetched: int
    inserted: int
    updated: int
    first_date: str | None
    last_date: str | None
    skipped: bool = False


def years_ago(day: date, years: int) -> date:
    if years < 1:
        raise ValueError("years must be >= 1")
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def _planned_ranges(start_day: date, end_day: date, coverage: dict, force: bool) -> list[tuple[date, date]]:
    """Plan only missing edge ranges.

    Backfill is a bootstrap operation. We intentionally avoid trying to infer
    internal exchange-holiday gaps from calendar dates. A later repair command
    can handle explicit integrity checks if needed.
    """
    if force or not coverage or not coverage.get("count"):
        return [(start_day, end_day)]

    first = coverage.get("first_date")
    last = coverage.get("last_date")
    if isinstance(first, str):
        first = date.fromisoformat(first)
    if isinstance(last, str):
        last = date.fromisoformat(last)

    ranges: list[tuple[date, date]] = []
    if first is None or last is None:
        return [(start_day, end_day)]

    # Missing older history.
    if first > start_day:
        older_end = min(end_day, first - timedelta(days=1))
        if start_day <= older_end:
            ranges.append((start_day, older_end))

    # Missing newer history.
    if last < end_day:
        newer_start = max(start_day, last + timedelta(days=1))
        if newer_start <= end_day:
            ranges.append((newer_start, end_day))

    return ranges


def _range_limit(start_day: date, end_day: date) -> int:
    # Approx. trading sessions plus headroom. REST service accepts <= 2000.
    calendar_days = max(1, (end_day - start_day).days + 1)
    return min(max(int(calendar_days * 5 / 7) + 30, 50), 2000)


def backfill_symbols(
    service: StockDataService,
    symbols: list[str] | None = None,
    years: int = 3,
    end_day: date | None = None,
    database_url: str | None = None,
    progress: Callable[[str], None] | None = None,
    force: bool = False,
) -> list[BackfillResult]:
    end_day = end_day or date.today()
    start_day = years_ago(end_day, years)
    instruments = get_active_instruments(symbols, database_url)
    results: list[BackfillResult] = []

    total = len(instruments)
    for index, instrument in enumerate(instruments, start=1):
        symbol = instrument["symbol"]
        coverage = candle_coverage(instrument["id"], database_url)
        ranges = _planned_ranges(start_day, end_day, coverage, force)

        if not ranges:
            first = coverage.get("first_date")
            last = coverage.get("last_date")
            if progress:
                progress(
                    f"[{index}/{total}] {symbol}: SKIP - DB already covers "
                    f"{first}..{last} ({coverage.get('count', 0)} candles)"
                )
            results.append(
                BackfillResult(
                    symbol=symbol,
                    provider=instrument.get("provider") or "db",
                    start=start_day.isoformat(),
                    end=end_day.isoformat(),
                    fetched=0,
                    inserted=0,
                    updated=0,
                    first_date=str(first) if first else None,
                    last_date=str(last) if last else None,
                    skipped=True,
                )
            )
            continue

        fetched_total = inserted_total = updated_total = 0
        provider_name = instrument.get("provider") or "vnstock"
        fetched_first: str | None = None
        fetched_last: str | None = None

        if progress:
            mode = "FORCE" if force else "SMART"
            progress(
                f"[{index}/{total}] {symbol}: {mode} backfill; "
                f"DB={coverage.get('count', 0)} candles, ranges={len(ranges)}"
            )

        try:
            for range_no, (fetch_start, fetch_end) in enumerate(ranges, start=1):
                if progress:
                    progress(
                        f"[{index}/{total}] {symbol}: range {range_no}/{len(ranges)} "
                        f"{fetch_start}..{fetch_end}"
                    )
                provider_result = service.daily_ohlcv(
                    symbol,
                    start=fetch_start.isoformat(),
                    end=fetch_end.isoformat(),
                    limit=_range_limit(fetch_start, fetch_end),
                )
                provider_name = provider_result.provider
                candles = provider_result.candles
                counts = upsert_daily_candles(
                    instrument_id=instrument["id"],
                    candles=candles,
                    provider=provider_name,
                    database_url=database_url,
                )
                fetched_total += len(candles)
                inserted_total += counts["inserted"]
                updated_total += counts["updated"]
                if candles:
                    fetched_first = fetched_first or candles[0]["date"]
                    fetched_last = candles[-1]["date"]

            final_coverage = candle_coverage(instrument["id"], database_url)
            last_sync = final_coverage.get("last_date")
            mark_sync_success(
                instrument["id"],
                str(last_sync) if last_sync else fetched_last,
                database_url,
            )
            results.append(
                BackfillResult(
                    symbol=symbol,
                    provider=provider_name,
                    start=start_day.isoformat(),
                    end=end_day.isoformat(),
                    fetched=fetched_total,
                    inserted=inserted_total,
                    updated=updated_total,
                    first_date=fetched_first or (str(final_coverage.get("first_date")) if final_coverage.get("first_date") else None),
                    last_date=fetched_last or (str(final_coverage.get("last_date")) if final_coverage.get("last_date") else None),
                )
            )
            if progress:
                progress(
                    f"[{index}/{total}] {symbol}: complete fetched={fetched_total} "
                    f"inserted={inserted_total} updated={updated_total}"
                )
        except Exception as exc:
            mark_sync_error(instrument["id"], str(exc), database_url)
            raise RuntimeError(f"Backfill failed for {symbol}: {exc}") from exc

    return results
