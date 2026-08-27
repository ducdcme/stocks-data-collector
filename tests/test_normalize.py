from app.normalize import normalize_ohlcv_rows


def test_normalize_common_vnstock_shape():
    rows = [
        {"time": "2026-08-21", "open": 100, "high": 105, "low": 99, "close": 104, "volume": 12345},
        {"time": "2026-08-20", "open": 98, "high": 101, "low": 97, "close": 100, "volume": 10000},
    ]
    result = normalize_ohlcv_rows(rows)
    assert [row["date"] for row in result] == ["2026-08-20", "2026-08-21"]
    assert result[-1]["close"] == 104


def test_duplicate_date_last_row_wins():
    result = normalize_ohlcv_rows([
        {"date": "2026-08-21", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10},
        {"date": "2026-08-21", "open": 100, "high": 103, "low": 99, "close": 102, "volume": 20},
    ])
    assert len(result) == 1
    assert result[0]["close"] == 102
