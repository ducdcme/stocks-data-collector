from pathlib import Path

import pytest

from app.config import Settings
from app.db import migration_files, require_database_url


def test_database_enabled_when_url_present(monkeypatch):
    monkeypatch.setenv("STOCKS_DATABASE_URL", "postgresql://localhost/stocks_data")
    settings = Settings()
    assert settings.database_enabled is True


def test_require_database_url_rejects_empty():
    with pytest.raises(RuntimeError, match="STOCKS_DATABASE_URL"):
        require_database_url("")


def test_initial_migration_contains_core_tables():
    files = migration_files(Path(__file__).resolve().parents[1] / "migrations")
    assert [p.name for p in files] == ["001_initial.sql", "002_corporate_action_events.sql"]
    sql = files[0].read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS instruments" in sql
    assert "CREATE TABLE IF NOT EXISTS daily_candles" in sql
    assert "CREATE TABLE IF NOT EXISTS sync_status" in sql
    assert "UNIQUE (instrument_id, trade_date)" in sql


def test_corporate_action_migration_contains_processed_event_state():
    files = migration_files(Path(__file__).resolve().parents[1] / "migrations")
    sql = files[1].read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS corporate_action_events" in sql
    assert "PRIMARY KEY (instrument_id, event_date)" in sql
    assert "reconciliation_updated" in sql
