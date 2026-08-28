from scripts.compare_providers import compare_rows


def row(day, value):
    return {"date": day, "open": value, "high": value + 1, "low": value - 1, "close": value + 0.5, "volume": 1}


def test_compare_rows_reports_provider_parity():
    ssi = [row("2026-08-10", 20.0), row("2026-08-11", 21.0)]
    vn = [row("2026-08-10", 20.01), row("2026-08-11", 21.01)]
    report = compare_rows(ssi, vn, tolerance=0.05, event_date="2026-08-11")
    assert report["before_event"]["changed_sessions"] == 0
    assert report["on_or_after_event"]["changed_sessions"] == 0


def test_compare_rows_separates_pre_event_mismatch():
    ssi = [row("2026-08-10", 24.0), row("2026-08-11", 20.0)]
    vn = [row("2026-08-10", 20.0), row("2026-08-11", 20.0)]
    report = compare_rows(ssi, vn, tolerance=0.05, event_date="2026-08-11")
    assert report["before_event"]["changed_ratio"] == 1.0
    assert report["on_or_after_event"]["changed_ratio"] == 0.0
