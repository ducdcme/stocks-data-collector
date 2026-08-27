from datetime import date

from app.backfill import backfill_symbols, years_ago
from app.service import ProviderResult


class FakeService:
    def __init__(self, candles):
        self.candles = candles
        self.calls = []

    def daily_ohlcv(self, symbol, start, end, limit):
        self.calls.append((symbol, start, end, limit))
        return ProviderResult(provider="vnstock", candles=self.candles)


def test_years_ago_handles_leap_day():
    assert years_ago(date(2024, 2, 29), 1) == date(2023, 2, 28)


def test_backfill_upserts_and_marks_success(monkeypatch):
    candles = [
        {"date": "2026-08-20", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000},
        {"date": "2026-08-21", "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 1200},
    ]
    service = FakeService(candles)
    monkeypatch.setattr(
        "app.backfill.get_active_instruments",
        lambda symbols, database_url=None: [
            {"id": 7, "symbol": "FPT", "exchange": "HOSE", "name": "FPT", "provider": "vnstock", "active": True}
        ],
    )
    coverage_calls = {"n": 0}
    def _coverage(*args, **kwargs):
        coverage_calls["n"] += 1
        if coverage_calls["n"] == 1:
            return {"count": 0, "first_date": None, "last_date": None}
        return {"count": 2, "first_date": date(2026, 8, 20), "last_date": date(2026, 8, 21)}
    monkeypatch.setattr("app.backfill.candle_coverage", _coverage)

    upserts = []
    successes = []
    monkeypatch.setattr(
        "app.backfill.upsert_daily_candles",
        lambda instrument_id, candles, provider, database_url=None: (
            upserts.append((instrument_id, candles, provider)) or
            {"received": len(candles), "inserted": 2, "updated": 0}
        ),
    )
    monkeypatch.setattr(
        "app.backfill.mark_sync_success",
        lambda instrument_id, last_sync_date, database_url=None: successes.append((instrument_id, last_sync_date)),
    )
    monkeypatch.setattr("app.backfill.mark_sync_error", lambda *args, **kwargs: None)

    results = backfill_symbols(
        service,
        symbols=["FPT"],
        years=3,
        end_day=date(2026, 8, 21),
        database_url="postgresql://test",
    )

    assert service.calls[0][:3] == ("FPT", "2023-08-21", "2026-08-21")
    assert service.calls[0][3] >= 500
    assert upserts[0][0] == 7
    assert successes == [(7, "2026-08-21")]
    assert results[0].fetched == 2
    assert results[0].inserted == 2
    assert results[0].updated == 0


def test_backfill_marks_error(monkeypatch):
    class FailingService:
        def daily_ohlcv(self, *args, **kwargs):
            raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(
        "app.backfill.get_active_instruments",
        lambda symbols, database_url=None: [{"id": 9, "symbol": "HPG"}],
    )
    monkeypatch.setattr(
        "app.backfill.candle_coverage",
        lambda *args, **kwargs: {"count": 0, "first_date": None, "last_date": None},
    )
    errors = []
    monkeypatch.setattr(
        "app.backfill.mark_sync_error",
        lambda instrument_id, error, database_url=None: errors.append((instrument_id, error)),
    )

    try:
        backfill_symbols(
            FailingService(),
            symbols=["HPG"],
            years=3,
            end_day=date(2026, 8, 21),
            database_url="postgresql://test",
        )
    except RuntimeError as exc:
        assert "HPG" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")

    assert errors == [(9, "upstream unavailable")]


def test_backfill_skips_when_db_already_covers_requested_range(monkeypatch):
    service = FakeService([])
    monkeypatch.setattr(
        "app.backfill.get_active_instruments",
        lambda symbols, database_url=None: [
            {"id": 7, "symbol": "DGC", "provider": "vnstock", "active": True}
        ],
    )
    monkeypatch.setattr(
        "app.backfill.candle_coverage",
        lambda instrument_id, database_url=None: {
            "count": 747,
            "first_date": date(2023, 8, 24),
            "last_date": date(2026, 8, 24),
        },
    )
    result = backfill_symbols(
        service,
        symbols=["DGC"],
        years=3,
        end_day=date(2026, 8, 24),
        database_url="postgresql://test",
    )[0]
    assert service.calls == []
    assert result.skipped is True
    assert result.fetched == 0


def test_backfill_fetches_only_missing_newer_edge(monkeypatch):
    candles = [
        {"date": "2026-08-24", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000},
    ]
    service = FakeService(candles)
    monkeypatch.setattr(
        "app.backfill.get_active_instruments",
        lambda symbols, database_url=None: [
            {"id": 7, "symbol": "FPT", "provider": "vnstock", "active": True}
        ],
    )
    calls = {"n": 0}
    def coverage(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"count": 746, "first_date": date(2023, 8, 24), "last_date": date(2026, 8, 21)}
        return {"count": 747, "first_date": date(2023, 8, 24), "last_date": date(2026, 8, 24)}
    monkeypatch.setattr("app.backfill.candle_coverage", coverage)
    monkeypatch.setattr(
        "app.backfill.upsert_daily_candles",
        lambda **kwargs: {"received": 1, "inserted": 1, "updated": 0},
    )
    monkeypatch.setattr("app.backfill.mark_sync_success", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.backfill.mark_sync_error", lambda *args, **kwargs: None)

    result = backfill_symbols(
        service,
        symbols=["FPT"],
        years=3,
        end_day=date(2026, 8, 24),
        database_url="postgresql://test",
    )[0]
    assert service.calls[0][1] == "2026-08-22"
    assert service.calls[0][2] == "2026-08-24"
    assert result.inserted == 1


def test_force_refetches_full_range(monkeypatch):
    service = FakeService([
        {"date": "2026-08-24", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000}
    ])
    monkeypatch.setattr(
        "app.backfill.get_active_instruments",
        lambda symbols, database_url=None: [{"id": 7, "symbol": "DGC", "provider": "vnstock", "active": True}],
    )
    monkeypatch.setattr(
        "app.backfill.candle_coverage",
        lambda *args, **kwargs: {"count": 747, "first_date": date(2023, 8, 24), "last_date": date(2026, 8, 24)},
    )
    monkeypatch.setattr(
        "app.backfill.upsert_daily_candles",
        lambda **kwargs: {"received": 1, "inserted": 0, "updated": 1},
    )
    monkeypatch.setattr("app.backfill.mark_sync_success", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.backfill.mark_sync_error", lambda *args, **kwargs: None)

    backfill_symbols(
        service,
        symbols=["DGC"],
        years=3,
        end_day=date(2026, 8, 24),
        database_url="postgresql://test",
        force=True,
    )
    assert service.calls[0][1] == "2023-08-24"
    assert service.calls[0][2] == "2026-08-24"
