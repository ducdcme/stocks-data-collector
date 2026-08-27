from app.providers.base import StockProvider
from app.service import StockDataService


class FakeProvider(StockProvider):
    def __init__(self, name, rows=None, error=None):
        self.name = name
        self.rows = rows or []
        self.error = error

    def daily_ohlcv(self, symbol, start, end, limit):
        if self.error:
            raise self.error
        return self.rows[-limit:]


def test_provider_fallback():
    service = StockDataService([
        FakeProvider("kbs", error=RuntimeError("temporary")),
        FakeProvider("vci", rows=[{"date": "2026-08-21", "close": 100}]),
    ])
    result = service.daily_ohlcv("FPT", None, None, 100)
    assert result.provider == "vci"
    assert len(result.candles) == 1


def test_provider_fallback_logs(caplog):
    import logging
    caplog.set_level(logging.WARNING)
    service = StockDataService([
        FakeProvider("ssi", error=RuntimeError("temporary")),
        FakeProvider("vnstock", rows=[{"date": "2026-08-25", "close": 100}]),
    ])
    result = service.daily_ohlcv("FPT", None, None, 100)
    assert result.provider == "vnstock"
    assert "falling back to vnstock" in caplog.text
