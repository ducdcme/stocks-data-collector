from app.catalog import SecurityCatalog


class Provider:
    name = "fake"

    def find_security(self, symbol):
        if symbol == "VCB":
            return {"symbol": "VCB", "exchange": "HOSE", "name": "Vietcombank"}
        return None


def test_catalog_finds_and_normalizes_symbol():
    row = SecurityCatalog([Provider()]).find(" vcb ")
    assert row.symbol == "VCB"
    assert row.exchange == "HOSE"
    assert row.name == "Vietcombank"
    assert row.provider == "fake"


def test_catalog_rejects_missing_symbol():
    try:
        SecurityCatalog([Provider()]).find("ZZZ")
    except ValueError as exc:
        assert "Không tìm thấy" in str(exc)
    else:
        raise AssertionError("expected ValueError")
