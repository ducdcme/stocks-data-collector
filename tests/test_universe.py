from app.universe import StockUniverseService


class FakeSSI:
    configured = True

    def index_components(self, index_code, page_size=1000):
        assert index_code == "VN30"
        return ["FPT", "MBB", "VCB"]

    def market_securities(self, market):
        rows = {
            "HOSE": [
                {"symbol": "FPT", "exchange": "HOSE", "name": "FPT"},
                {"symbol": "MBB", "exchange": "HOSE", "name": "MB Bank"},
                {"symbol": "VCB", "exchange": "HOSE", "name": "Vietcombank"},
                {"symbol": "HPG", "exchange": "HOSE", "name": "Hoa Phat"},
            ],
            "HNX": [{"symbol": "PVS", "exchange": "HNX", "name": "PVS"}],
            "UPCOM": [{"symbol": "ACV", "exchange": "UPCOM", "name": "ACV"}],
        }
        return rows.get(market, [])


def active_rows():
    return [
        {"symbol": "FPT", "exchange": "HOSE", "name": "FPT", "provider": "ssi"},
        {"symbol": "HPG", "exchange": "HOSE", "name": "Hoa Phat", "provider": "ssi"},
        {"symbol": "PVS", "exchange": "HNX", "name": "PVS", "provider": "ssi"},
    ]


def test_vn30_returns_only_prepared_intersection(monkeypatch):
    monkeypatch.setattr("app.universe.list_instruments", lambda active_only=True: active_rows())
    service = StockUniverseService(FakeSSI())
    row = service.group("VN30")
    assert row.total == 3
    assert [item["symbol"] for item in row.prepared] == ["FPT"]
    assert row.missing == ["MBB", "VCB"]


def test_exchange_group_reports_prepared_and_missing(monkeypatch):
    monkeypatch.setattr("app.universe.list_instruments", lambda active_only=True: active_rows())
    service = StockUniverseService(FakeSSI())
    row = service.group("HOSE")
    assert row.total == 4
    assert [item["symbol"] for item in row.prepared] == ["FPT", "HPG"]
    assert row.missing == ["MBB", "VCB"]


def test_database_fallback_does_not_invent_vn30(monkeypatch):
    monkeypatch.setattr("app.universe.list_instruments", lambda active_only=True: active_rows())
    service = StockUniverseService(None)
    assert service.group("VN30").total == 0
    hose = service.group("HOSE")
    assert hose.provider == "database"
    assert [item["symbol"] for item in hose.prepared] == ["FPT", "HPG"]


class NoDataSSI(FakeSSI):
    def index_components(self, index_code, page_size=1000):
        raise RuntimeError("SSI IndexComponents failed: There is no data")

    def market_securities(self, market):
        raise RuntimeError("SSI Securities failed: There is no data")


class ToggleNoDataSSI(FakeSSI):
    def __init__(self):
        self.no_data = False

    def index_components(self, index_code, page_size=1000):
        if self.no_data:
            raise RuntimeError("SSI IndexComponents failed: There is no data")
        return super().index_components(index_code, page_size)

    def market_securities(self, market):
        if self.no_data:
            raise RuntimeError("SSI Securities failed: There is no data")
        return super().market_securities(market)


def test_holiday_no_data_exchange_falls_back_to_active_database(monkeypatch):
    monkeypatch.setattr("app.universe.list_instruments", lambda active_only=True: active_rows())
    service = StockUniverseService(NoDataSSI())
    row = service.group("HOSE")
    assert row.provider == "database-fallback"
    assert row.total == 2
    assert [item["symbol"] for item in row.prepared] == ["FPT", "HPG"]
    assert row.missing == []


def test_holiday_no_data_vn30_without_cache_does_not_invent_membership(monkeypatch):
    monkeypatch.setattr("app.universe.list_instruments", lambda active_only=True: active_rows())
    service = StockUniverseService(NoDataSSI())
    row = service.group("VN30")
    assert row.provider == "database-fallback"
    assert row.total == 0
    assert row.prepared == []
    assert row.missing == []


def test_holiday_no_data_uses_stale_last_successful_ssi_cache(monkeypatch):
    monkeypatch.setattr("app.universe.list_instruments", lambda active_only=True: active_rows())
    ssi = ToggleNoDataSSI()
    service = StockUniverseService(ssi, ttl_seconds=30)

    first = service.group("HOSE")
    assert first.provider == "ssi"
    assert first.total == 4

    # Force the successful cache to be expired while keeping it available as
    # last-known-good data, then simulate SSI holiday/no-data.
    ts, rows = service._cache["HOSE"]
    service._cache["HOSE"] = (ts - 3600, rows)
    ssi.no_data = True

    fallback = service.group("HOSE")
    assert fallback.provider == "ssi-cache"
    assert fallback.total == 4
    assert [item["symbol"] for item in fallback.prepared] == ["FPT", "HPG"]
    assert fallback.missing == ["MBB", "VCB"]


def test_holiday_no_data_groups_endpoint_logic_stays_available(monkeypatch):
    monkeypatch.setattr("app.universe.list_instruments", lambda active_only=True: active_rows())
    rows = StockUniverseService(NoDataSSI()).groups()
    assert [row["group"] for row in rows] == ["VN30", "HOSE", "HNX", "UPCOM"]
    assert rows[0]["provider"] == "database-fallback"
    assert rows[1]["preparedCount"] == 2
    assert rows[2]["preparedCount"] == 1
    assert rows[3]["preparedCount"] == 0
