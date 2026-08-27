from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.daily_sync import completed_market_date, sync_daily
from app.service import ProviderResult


class FakeService:
    def __init__(self, candles):
        self.candles = candles
        self.calls = []

    def daily_ohlcv(self, symbol, start, end, limit, empty_ok=False):
        self.calls.append((symbol, start, end, limit, empty_ok))
        return ProviderResult(provider="vnstock", candles=self.candles)


def test_completed_market_date_before_close_uses_previous_day():
    now = datetime(2026, 8, 25, 9, 43, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    assert completed_market_date(now) == date(2026, 8, 24)


def test_completed_market_date_after_close_uses_today():
    now = datetime(2026, 8, 25, 15, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    assert completed_market_date(now) == date(2026, 8, 25)


def test_sync_skips_when_database_is_current(monkeypatch):
    service = FakeService([])
    monkeypatch.setattr(
        "app.daily_sync.get_active_instruments",
        lambda symbols, database_url=None: [{"id": 1, "symbol": "FPT", "provider": "vnstock"}],
    )
    monkeypatch.setattr(
        "app.daily_sync.candle_coverage",
        lambda *args, **kwargs: {"count": 747, "first_date": date(2023, 8, 24), "last_date": date(2026, 8, 24)},
    )

    result = sync_daily(service, symbols=["FPT"], as_of=date(2026, 8, 24), database_url="postgresql://test")[0]
    assert result.skipped is True
    assert service.calls == []


def test_sync_fetches_only_newer_dates(monkeypatch):
    candles = [{"date": "2026-08-25", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}]
    service = FakeService(candles)
    monkeypatch.setattr(
        "app.daily_sync.get_active_instruments",
        lambda symbols, database_url=None: [{"id": 1, "symbol": "FPT", "provider": "vnstock"}],
    )
    monkeypatch.setattr(
        "app.daily_sync.candle_coverage",
        lambda *args, **kwargs: {"count": 747, "first_date": date(2023, 8, 24), "last_date": date(2026, 8, 24)},
    )
    monkeypatch.setattr(
        "app.daily_sync.upsert_daily_candles",
        lambda **kwargs: {"received": 1, "inserted": 1, "updated": 0},
    )
    successes = []
    monkeypatch.setattr(
        "app.daily_sync.mark_sync_success",
        lambda instrument_id, last_sync_date, database_url=None: successes.append((instrument_id, last_sync_date)),
    )
    monkeypatch.setattr("app.daily_sync.mark_sync_error", lambda *args, **kwargs: None)

    result = sync_daily(service, symbols=["FPT"], as_of=date(2026, 8, 25), database_url="postgresql://test")[0]
    assert service.calls[0][1] == "2026-08-24"
    assert service.calls[0][2] == "2026-08-25"
    assert service.calls[0][4] is True
    assert result.inserted == 1
    assert successes == [(1, "2026-08-25")]


def test_sync_empty_non_trading_range_is_success(monkeypatch):
    service = FakeService([{"date": "2026-08-21", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}])
    monkeypatch.setattr(
        "app.daily_sync.get_active_instruments",
        lambda symbols, database_url=None: [{"id": 1, "symbol": "FPT", "provider": "vnstock"}],
    )
    monkeypatch.setattr(
        "app.daily_sync.candle_coverage",
        lambda *args, **kwargs: {"count": 747, "first_date": date(2023, 8, 24), "last_date": date(2026, 8, 21)},
    )
    monkeypatch.setattr(
        "app.daily_sync.upsert_daily_candles",
        lambda **kwargs: {"received": 0, "inserted": 0, "updated": 0},
    )
    successes = []
    monkeypatch.setattr(
        "app.daily_sync.mark_sync_success",
        lambda instrument_id, last_sync_date, database_url=None: successes.append((instrument_id, last_sync_date)),
    )
    monkeypatch.setattr("app.daily_sync.mark_sync_error", lambda *args, **kwargs: None)

    result = sync_daily(service, symbols=["FPT"], as_of=date(2026, 8, 23), database_url="postgresql://test")[0]
    assert result.fetched == 0
    assert result.reason == "no trading candle in requested range"
    assert successes == [(1, "2026-08-21")]


def test_completed_market_date_monday_morning_rolls_back_to_friday():
    now = datetime(2026, 8, 24, 7, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    assert completed_market_date(now) == date(2026, 8, 21)


def test_completed_market_date_sunday_rolls_back_to_friday():
    now = datetime(2026, 8, 23, 16, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    assert completed_market_date(now) == date(2026, 8, 21)
