from pathlib import Path


def test_repository_uses_upsert_for_daily_candles():
    source = (Path(__file__).resolve().parents[1] / "app" / "repository.py").read_text(encoding="utf-8")
    assert "ON CONFLICT (instrument_id, trade_date) DO UPDATE" in source
    assert "updated_at = now()" in source


def test_backfill_command_exists():
    path = Path(__file__).resolve().parents[1] / "scripts" / "backfill.py"
    assert path.exists()
    source = path.read_text(encoding="utf-8")
    assert "--symbols" in source
    assert "--years" in source


def test_repository_has_database_candle_reader():
    source = (Path(__file__).resolve().parents[1] / "app" / "repository.py").read_text(encoding="utf-8")
    assert "def get_daily_candles(" in source
    assert "ORDER BY trade_date DESC LIMIT %s" in source


def test_repository_has_dynamic_instrument_management():
    source = (Path(__file__).resolve().parents[1] / "app" / "repository.py").read_text(encoding="utf-8")
    assert "def list_instruments(" in source
    assert "def upsert_instrument(" in source
    assert "def get_instrument(" in source
    assert "def activate_instrument(" in source
    assert "def deactivate_instrument(" in source
    assert "active = false" in source
