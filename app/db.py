from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def require_database_url(database_url: str | None = None) -> str:
    url = (database_url if database_url is not None else settings.database_url).strip()
    if not url:
        raise RuntimeError("STOCKS_DATABASE_URL is not configured")
    return url


def _psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL support is not installed. Run: pip install -r requirements.txt"
        ) from exc
    return psycopg, dict_row


def connect(database_url: str | None = None):
    url = require_database_url(database_url)
    psycopg, dict_row = _psycopg()
    return psycopg.connect(
        url,
        connect_timeout=settings.db_connect_timeout,
        row_factory=dict_row,
    )


def ping(database_url: str | None = None) -> dict[str, Any]:
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database() AS database, now() AS server_time")
            row = cur.fetchone()
    return dict(row or {})


def migration_files(migrations_dir: Path | None = None) -> list[Path]:
    directory = migrations_dir or MIGRATIONS_DIR
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.sql") if path.is_file())


def migrate(database_url: str | None = None, migrations_dir: Path | None = None) -> list[str]:
    files = migration_files(migrations_dir)
    if not files:
        return []

    applied: list[str] = []
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version text PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            for path in files:
                version = path.name
                cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
                if cur.fetchone():
                    continue
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (version,))
                applied.append(version)
        conn.commit()
    return applied
