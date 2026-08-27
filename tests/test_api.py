from fastapi.testclient import TestClient

import app.main as main
from app.providers.base import StockProvider
from app.service import StockDataService


class ApiFakeProvider(StockProvider):
    name = "fake"

    def daily_ohlcv(self, symbol, start, end, limit):
        return [{"date": "2026-08-21", "open": 100, "high": 105, "low": 99, "close": 104, "volume": 10}]


def test_health_and_candles(monkeypatch):
    monkeypatch.setattr(main, "service", StockDataService([ApiFakeProvider()]))
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200
    response = client.get("/candles/d1", params={"symbol": "fpt", "limit": 20})
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "FPT"
    assert body["provider"] == "fake"
    assert body["candles"][0]["close"] == 104


def test_candles_reads_database_when_configured(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(main, "settings", SimpleNamespace(database_enabled=True))
    monkeypatch.setattr(
        main,
        "get_daily_candles",
        lambda symbol, start, end, limit: [{"date": "2026-08-21", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0}],
    )
    client = TestClient(main.app)
    response = client.get("/candles/d1", params={"symbol": "FPT", "limit": 20})
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "database"
    assert body["count"] == 1


def _db_settings():
    from types import SimpleNamespace
    return SimpleNamespace(database_enabled=True, min_prepared_candles=100)


def test_admin_add_current_partial_data_ignores_old_error_state_and_skips_provider(monkeypatch):
    monkeypatch.setattr(main, "settings", _db_settings())
    monkeypatch.setattr(main, "completed_market_date", lambda: __import__('datetime').date(2026, 8, 26))
    monkeypatch.setattr(main, "get_instrument", lambda symbol: {
        "id": 7, "symbol": "FPT", "exchange": "HOSE", "name": "FPT", "provider": "ssi", "active": True
    })
    monkeypatch.setattr(main, "candle_coverage", lambda *args, **kwargs: {
        "count": 23, "first_date": "2026-07-27", "last_date": "2026-08-26"
    })
    monkeypatch.setattr(main, "backfill_symbols", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("current DB must not backfill")))
    monkeypatch.setattr(main, "sync_daily", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("current DB must not sync")))
    client = TestClient(main.app)
    response = client.post("/admin/instruments", json={"symbol": "FPT", "years": 3})
    assert response.status_code == 200
    body = response.json()["backfill"]
    assert body["operation"] == "current"
    assert body["provider"] == "database"
    assert body["candle_count"] == 23
    assert body["chartable"] is True
    assert body["ready_for_signal"] is False

def test_admin_add_current_db_skips_provider_regardless_of_signal_count(monkeypatch):
    monkeypatch.setattr(main, "settings", _db_settings())
    monkeypatch.setattr(main, "completed_market_date", lambda: __import__('datetime').date(2026, 8, 26))
    monkeypatch.setattr(main, "get_instrument", lambda symbol: {
        "id": 8, "symbol": "NEW", "exchange": "HOSE", "name": "New Listing", "provider": "ssi", "active": True
    })
    monkeypatch.setattr(main, "candle_coverage", lambda *args, **kwargs: {
        "count": 63, "first_date": "2026-05-25", "last_date": "2026-08-26"
    })
    monkeypatch.setattr(main.catalog, "find", lambda symbol: (_ for _ in ()).throw(AssertionError("catalog/provider must not be called")))
    monkeypatch.setattr(main, "backfill_symbols", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("backfill/provider must not be called")))
    monkeypatch.setattr(main, "sync_daily", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sync/provider must not be called")))
    client = TestClient(main.app)
    response = client.post("/admin/instruments", json={"symbol": "NEW", "years": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["backfill"]["operation"] == "current"
    assert body["backfill"]["skipped"] is True
    assert body["backfill"]["candle_count"] == 63
    assert body["backfill"]["chartable"] is True
    assert body["backfill"]["ready_for_signal"] is False


def test_admin_add_current_747_candles_skips_provider(monkeypatch):
    monkeypatch.setattr(main, "settings", _db_settings())
    monkeypatch.setattr(main, "completed_market_date", lambda: __import__('datetime').date(2026, 8, 26))
    monkeypatch.setattr(main, "get_instrument", lambda symbol: {
        "id": 8, "symbol": "VIX", "exchange": "HOSE", "name": "VIX Securities", "provider": "ssi", "active": True
    })
    monkeypatch.setattr(main, "candle_coverage", lambda *args, **kwargs: {
        "count": 747, "first_date": "2023-08-24", "last_date": "2026-08-26"
    })
    monkeypatch.setattr(main, "backfill_symbols", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("backfill/provider must not be called")))
    monkeypatch.setattr(main, "sync_daily", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sync/provider must not be called")))
    client = TestClient(main.app)
    response = client.post("/admin/instruments", json={"symbol": "VIX", "years": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["backfill"]["provider"] == "database"
    assert body["backfill"]["ready_for_signal"] is True


def test_admin_add_stale_existing_uses_daily_sync_not_full_backfill(monkeypatch):
    monkeypatch.setattr(main, "settings", _db_settings())
    monkeypatch.setattr(main, "completed_market_date", lambda: __import__('datetime').date(2026, 8, 26))
    monkeypatch.setattr(main, "get_instrument", lambda symbol: {
        "id": 10, "symbol": "FPT", "exchange": "HOSE", "name": "FPT", "provider": "ssi", "active": True
    })
    coverage = {"count": 746, "first_date": "2023-08-24", "last_date": "2026-08-25"}
    monkeypatch.setattr(main, "candle_coverage", lambda *args, **kwargs: coverage)
    monkeypatch.setattr(main, "backfill_symbols", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full backfill must not be called")))
    calls = []
    class R:
        provider = "ssi"; fetched = 1; inserted = 1; updated = 0; skipped = False
    def fake_sync(*args, **kwargs):
        calls.append(kwargs)
        coverage.update({"count": 747, "last_date": "2026-08-26"})
        return [R()]
    monkeypatch.setattr(main, "sync_daily", fake_sync)
    client = TestClient(main.app)
    response = client.post("/admin/instruments", json={"symbol": "FPT", "years": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["backfill"]["operation"] == "sync"
    assert body["backfill"]["inserted"] == 1
    assert calls and calls[0]["as_of"].isoformat() == "2026-08-26"


def test_admin_add_current_747_candles_ignores_historical_error_and_calls_no_provider(monkeypatch):
    monkeypatch.setattr(main, "settings", _db_settings())
    monkeypatch.setattr(main, "completed_market_date", lambda: __import__('datetime').date(2026, 8, 26))
    monkeypatch.setattr(main, "get_instrument", lambda symbol: {
        "id": 11, "symbol": "HPG", "exchange": "HOSE", "name": "Hoa Phat Group", "provider": "ssi", "active": True
    })
    monkeypatch.setattr(main, "candle_coverage", lambda *args, **kwargs: {
        "count": 747, "first_date": "2023-08-28", "last_date": "2026-08-26"
    })
    monkeypatch.setattr(main, "backfill_symbols", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("historical error must not force backfill")))
    monkeypatch.setattr(main, "sync_daily", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("current DB must not sync")))
    client = TestClient(main.app)
    response = client.post("/admin/instruments", json={"symbol": "HPG", "years": 3})
    assert response.status_code == 200
    body = response.json()["backfill"]
    assert body["operation"] == "current"
    assert body["provider"] == "database"
    assert body["skipped"] is True
    assert body["candle_count"] == 747


def test_admin_add_stale_symbol_with_historical_error_uses_daily_sync(monkeypatch):
    monkeypatch.setattr(main, "settings", _db_settings())
    monkeypatch.setattr(main, "completed_market_date", lambda: __import__('datetime').date(2026, 8, 26))
    monkeypatch.setattr(main, "get_instrument", lambda symbol: {
        "id": 12, "symbol": "MBB", "exchange": "HOSE", "name": "MB Bank", "provider": "ssi", "active": True
    })
    coverage = {"count": 746, "first_date": "2023-08-28", "last_date": "2026-08-25"}
    monkeypatch.setattr(main, "candle_coverage", lambda *args, **kwargs: coverage)
    monkeypatch.setattr(main, "backfill_symbols", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("existing stale symbol must not bootstrap")))
    class R:
        provider = "ssi"; fetched = 1; inserted = 1; updated = 0; skipped = False
    def fake_sync(*args, **kwargs):
        coverage.update({"count": 747, "last_date": "2026-08-26"})
        return [R()]
    monkeypatch.setattr(main, "sync_daily", fake_sync)
    client = TestClient(main.app)
    response = client.post("/admin/instruments", json={"symbol": "MBB", "years": 3})
    assert response.status_code == 200
    assert response.json()["backfill"]["operation"] == "sync"

def test_admin_add_reactivates_existing_current_symbol_without_provider(monkeypatch):
    monkeypatch.setattr(main, "settings", _db_settings())
    monkeypatch.setattr(main, "completed_market_date", lambda: __import__('datetime').date(2026, 8, 26))
    monkeypatch.setattr(main, "get_instrument", lambda symbol: {
        "id": 9, "symbol": "HPG", "exchange": "HOSE", "name": "Hoa Phat Group", "provider": "ssi", "active": False
    })
    activated = []
    monkeypatch.setattr(main, "activate_instrument", lambda symbol: activated.append(symbol) or {
        "id": 9, "symbol": "HPG", "exchange": "HOSE", "name": "Hoa Phat Group", "provider": "ssi", "active": True
    })
    monkeypatch.setattr(main, "candle_coverage", lambda *args, **kwargs: {
        "count": 500, "first_date": "2024-08-01", "last_date": "2026-08-26"
    })
    monkeypatch.setattr(main, "backfill_symbols", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must skip provider")))
    monkeypatch.setattr(main, "sync_daily", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must skip provider")))
    client = TestClient(main.app)
    response = client.post("/admin/instruments", json={"symbol": "HPG", "years": 3})
    assert response.status_code == 200
    assert activated == ["HPG"]
