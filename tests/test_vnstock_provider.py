from datetime import date, timedelta

from app.providers.vnstock_provider import VnstockProvider


def _weekday_rows(start_text: str, end_text: str):
    start = date.fromisoformat(start_text)
    end = date.fromisoformat(end_text)
    rows = []
    current = start
    value = 10.0
    while current <= end:
        if current.weekday() < 5:
            rows.append({
                "date": current.isoformat(),
                "open": value,
                "high": value + 1,
                "low": value - 1,
                "close": value + 0.5,
                "volume": 1000,
            })
            value += 0.01
        current += timedelta(days=1)
    return rows


def test_long_history_is_chunked_and_can_return_500(monkeypatch):
    provider = VnstockProvider(requests_per_minute=100000)
    calls = []

    def fake_fetch(symbol, start_date, end_date):
        calls.append((start_date, end_date))
        # Simulate an upstream hard cap of 100 rows per request.
        return _weekday_rows(start_date, end_date)[-100:]

    monkeypatch.setattr(provider, "_fetch_ohlcv", fake_fetch)

    rows = provider.daily_ohlcv(
        "FPT",
        start="2023-01-01",
        end="2026-08-21",
        limit=500,
    )

    assert len(rows) == 500
    assert rows == sorted(rows, key=lambda item: item["date"])
    assert len({row["date"] for row in rows}) == 500
    assert len(calls) > 1
    # Each chunk is deliberately small enough to avoid a 100-session cap.
    assert all(len(_weekday_rows(start, end)) < 100 for start, end in calls)


def test_invalid_date_range():
    provider = VnstockProvider()
    try:
        provider.daily_ohlcv("FPT", "2026-08-22", "2026-08-21", 20)
    except ValueError as exc:
        assert "start" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_throttle_waits_between_requests(monkeypatch):
    provider = VnstockProvider(requests_per_minute=15)
    clock = {"now": 100.0}
    sleeps = []

    monkeypatch.setattr("app.providers.vnstock_provider.time.monotonic", lambda: clock["now"])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr("app.providers.vnstock_provider.time.sleep", fake_sleep)

    provider._throttle()
    clock["now"] += 1.0
    provider._throttle()

    assert sleeps == [3.0]


def test_rate_limit_is_retried_after_cooldown(monkeypatch):
    provider = VnstockProvider(
        requests_per_minute=60,
        retry_wait_seconds=65,
        max_rate_limit_retries=2,
    )
    attempts = []
    sleeps = []
    clock = {"now": 100.0}

    monkeypatch.setattr("app.providers.vnstock_provider.time.monotonic", lambda: clock["now"])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr("app.providers.vnstock_provider.time.sleep", fake_sleep)

    def fake_fetch(symbol, start_date, end_date):
        attempts.append((symbol, start_date, end_date))
        if len(attempts) == 1:
            raise RuntimeError("Rate Limit Exceeded: 20/20 requests")
        return _weekday_rows(start_date, end_date)

    monkeypatch.setattr(provider, "_fetch_ohlcv", fake_fetch)

    frame = provider._fetch_ohlcv_with_retry("FPT", "2026-08-01", "2026-08-21")

    assert len(attempts) == 2
    assert 65 in sleeps
    assert len(frame) > 0


def test_default_rate_is_conservative(monkeypatch):
    monkeypatch.delenv("VNSTOCK_REQUESTS_PER_MINUTE", raising=False)
    provider = VnstockProvider()
    assert provider.requests_per_minute == 8


def test_empty_historical_chunk_retries(monkeypatch):
    provider = VnstockProvider(requests_per_minute=100000, retry_wait_seconds=1, max_rate_limit_retries=2)
    calls = {"n": 0}

    def fake_fetch(symbol, start_date, end_date):
        calls["n"] += 1
        if calls["n"] == 1:
            return []
        return [{"time": start_date, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}]

    monkeypatch.setattr(provider, "_fetch_ohlcv", fake_fetch)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    records = provider._fetch_ohlcv_with_retry("FPT", "2024-01-01", "2024-04-01")
    assert calls["n"] == 2
    assert len(records) == 1


def test_find_security_resolves_exchange_from_list_by_exchange_when_list_omits_exchange(monkeypatch):
    provider = VnstockProvider(requests_per_minute=100000)

    class Equity:
        def list(self):
            return [{"symbol": "HAG", "organ_name": "Hoang Anh Gia Lai"}]

        def list_by_exchange(self):
            return [{"symbol": "HAG", "exchange": "HOSE"}]

    class Reference:
        equity = Equity()

    monkeypatch.setattr(VnstockProvider, "_reference", staticmethod(lambda: Reference()))
    monkeypatch.setattr(provider, "_throttle", lambda: None)

    row = provider.find_security("HAG")

    assert row == {"symbol": "HAG", "exchange": "HOSE", "name": "Hoang Anh Gia Lai"}


def test_find_security_resolves_exchange_from_group_when_exchange_list_has_no_exchange_column(monkeypatch):
    provider = VnstockProvider(requests_per_minute=100000)

    class Equity:
        def list(self):
            return [{"symbol": "HDG", "organ_name": "Ha Do"}]

        def list_by_exchange(self):
            return [{"symbol": "HDG"}]

        def list_by_group(self, group=None):
            return [{"symbol": "HDG"}] if group == "HOSE" else []

    class Reference:
        equity = Equity()

    monkeypatch.setattr(VnstockProvider, "_reference", staticmethod(lambda: Reference()))
    monkeypatch.setattr(provider, "_throttle", lambda: None)

    row = provider.find_security("HDG")

    assert row == {"symbol": "HDG", "exchange": "HOSE", "name": "Ha Do"}


def test_find_security_survives_all_symbols_no_data_using_exchange_membership(monkeypatch):
    provider = VnstockProvider(requests_per_minute=100000)

    class Equity:
        def list(self):
            raise RuntimeError("There is no data")

        def list_by_exchange(self):
            raise RuntimeError("There is no data")

        def list_by_group(self, group=None):
            return [{"symbol": "TRA"}] if group == "HOSE" else []

    class Reference:
        equity = Equity()

    monkeypatch.setattr(VnstockProvider, "_reference", staticmethod(lambda: Reference()))
    monkeypatch.setattr(provider, "_throttle", lambda: None)

    row = provider.find_security("TRA")

    assert row == {"symbol": "TRA", "exchange": "HOSE", "name": "TRA"}
