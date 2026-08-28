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


class FakeSSIProvider:
    name = "ssi"

    def __init__(self, factors, history):
        self.factors = factors
        self.history = history
        self.factor_calls = []
        self.history_calls = []

    def daily_adjustment_factors(self, symbol, market, start, end):
        self.factor_calls.append((symbol, market, start, end))
        return self.factors

    def daily_ohlcv(self, symbol, start, end, limit):
        self.history_calls.append((symbol, start, end, limit))
        return self.history


class FakeProviderService:
    def __init__(self, provider):
        self.providers = [provider]


def _ca_candle(day, value):
    return {
        "date": day,
        "open": value,
        "high": value + 1,
        "low": value - 1,
        "close": value + 0.2,
        "volume": 100,
        "provider": "ssi",
    }


def test_auto_corporate_action_reconciles_new_ssi_event_once(monkeypatch):
    from app.daily_sync import _auto_corporate_action_reconciliation

    factors = [
        {"date": "2026-08-10", "factor": 0.833},
        {"date": "2026-08-11", "factor": 1.0},
        {"date": "2026-08-12", "factor": 1.0},
    ]
    db_rows = [_ca_candle("2026-08-10", 24), _ca_candle("2026-08-11", 20)]
    ssi_rows = [_ca_candle("2026-08-10", 20), _ca_candle("2026-08-11", 20)]
    provider = FakeSSIProvider(factors, ssi_rows)

    monkeypatch.setattr("app.daily_sync.processed_corporate_action_dates", lambda *a, **k: set())
    monkeypatch.setattr("app.daily_sync.get_instrument_candles_with_provider", lambda *a, **k: db_rows)
    applied = []

    def fake_apply(**kwargs):
        applied.append(kwargs)
        return {"updated": 1, "inserted": 0, "events_recorded": 1}

    monkeypatch.setattr("app.daily_sync.apply_corporate_action_reconciliation", fake_apply)

    result = _auto_corporate_action_reconciliation(
        service=FakeProviderService(provider),
        instrument={"id": 1, "symbol": "MBB", "exchange": "HOSE"},
        target=date(2026, 8, 12),
        database_url="postgresql://test",
        progress=None,
        lookback_days=10,
        factor_tolerance=0.0005,
        price_tolerance=0.05,
    )

    assert result.detected_events == ["2026-08-11"]
    assert result.new_events == ["2026-08-11"]
    assert result.updated == 1
    assert result.events_recorded == 1
    assert result.status == "reconciled"
    assert applied[0]["processed_events"][0]["event_date"] == "2026-08-11"


def test_auto_corporate_action_skips_event_already_processed(monkeypatch):
    from app.daily_sync import _auto_corporate_action_reconciliation

    provider = FakeSSIProvider(
        [
            {"date": "2026-08-10", "factor": 0.833},
            {"date": "2026-08-11", "factor": 1.0},
        ],
        [],
    )
    monkeypatch.setattr(
        "app.daily_sync.processed_corporate_action_dates",
        lambda *a, **k: {"2026-08-11"},
    )
    monkeypatch.setattr(
        "app.daily_sync.get_instrument_candles_with_provider",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("history should not be loaded")),
    )

    result = _auto_corporate_action_reconciliation(
        service=FakeProviderService(provider),
        instrument={"id": 1, "symbol": "MBB", "exchange": "HOSE"},
        target=date(2026, 8, 12),
        database_url="postgresql://test",
        progress=None,
        lookback_days=10,
        factor_tolerance=0.0005,
        price_tolerance=0.05,
    )

    assert result.new_events == []
    assert result.already_processed_events == ["2026-08-11"]
    assert result.status == "events_already_processed"
    assert provider.history_calls == []


def test_sync_checks_corporate_actions_even_when_edge_is_current(monkeypatch):
    from app.daily_sync import CorporateActionDailyResult

    service = FakeService([])
    monkeypatch.setattr(
        "app.daily_sync.get_active_instruments",
        lambda symbols, database_url=None: [
            {"id": 1, "symbol": "FPT", "exchange": "HOSE", "provider": "ssi"}
        ],
    )
    monkeypatch.setattr(
        "app.daily_sync.candle_coverage",
        lambda *args, **kwargs: {
            "count": 747,
            "first_date": date(2023, 8, 24),
            "last_date": date(2026, 8, 24),
        },
    )
    checks = []

    def fake_ca(**kwargs):
        checks.append(kwargs["instrument"]["symbol"])
        return CorporateActionDailyResult(enabled=True, checked=True, status="checked_no_event")

    monkeypatch.setattr("app.daily_sync._auto_corporate_action_reconciliation", fake_ca)

    result = sync_daily(
        service,
        symbols=["FPT"],
        as_of=date(2026, 8, 24),
        database_url="postgresql://test",
    )[0]
    assert result.skipped is True
    assert checks == ["FPT"]
    assert result.corporate_action.status == "checked_no_event"
