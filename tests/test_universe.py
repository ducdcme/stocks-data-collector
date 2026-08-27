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
