from __future__ import annotations

TEST_SYMBOLS = (
    {"symbol": "FPT", "exchange": "HOSE", "name": "FPT"},
    {"symbol": "HPG", "exchange": "HOSE", "name": "Hoa Phat Group"},
    {"symbol": "MBB", "exchange": "HOSE", "name": "MB Bank"},
    {"symbol": "DGC", "exchange": "HOSE", "name": "Duc Giang Chemicals"},
    {"symbol": "VIX", "exchange": "HOSE", "name": "VIX Securities"},
)


def normalize_symbol(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol or not symbol.replace("-", "").isalnum():
        raise ValueError("Invalid stock symbol")
    return symbol


def test_symbol_rows() -> list[dict]:
    return [dict(item) for item in TEST_SYMBOLS]
