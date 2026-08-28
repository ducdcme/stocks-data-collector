from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from .db import connect


def get_active_instruments(symbols: Iterable[str] | None = None, database_url: str | None = None) -> list[dict[str, Any]]:
    requested = [s.strip().upper() for s in (symbols or []) if s and s.strip()]
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            if requested:
                cur.execute(
                    """
                    SELECT id, symbol, exchange, name, provider, active
                    FROM instruments
                    WHERE active = true AND symbol = ANY(%s)
                    ORDER BY symbol
                    """,
                    (requested,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, symbol, exchange, name, provider, active
                    FROM instruments
                    WHERE active = true
                    ORDER BY symbol
                    """
                )
            rows = [dict(row) for row in cur.fetchall()]

    if requested:
        found = {row["symbol"] for row in rows}
        missing = sorted(set(requested) - found)
        if missing:
            raise ValueError("Unknown or inactive symbols: " + ", ".join(missing))
    return rows



def get_instrument(symbol: str, database_url: str | None = None) -> dict[str, Any] | None:
    """Return one instrument regardless of active state."""
    normalized = symbol.strip().upper()
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, symbol, exchange, name, provider, active, created_at, updated_at
                FROM instruments
                WHERE symbol = %s
                ORDER BY active DESC, id
                LIMIT 1
                """,
                (normalized,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_sync_status(instrument_id: int, database_url: str | None = None) -> dict[str, Any]:
    """Return persisted sync state for one instrument."""
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instrument_id, last_sync_date, status, error_count, last_error,
                       last_attempt_at, last_success_at, updated_at
                FROM sync_status
                WHERE instrument_id = %s
                """,
                (instrument_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else {
                "instrument_id": instrument_id,
                "last_sync_date": None,
                "status": "never",
                "error_count": 0,
                "last_error": None,
            }


def activate_instrument(symbol: str, database_url: str | None = None) -> dict[str, Any]:
    """Reactivate an existing instrument without touching its metadata/history."""
    normalized = symbol.strip().upper()
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE instruments
                SET active = true, updated_at = now()
                WHERE symbol = %s
                RETURNING id, symbol, exchange, name, provider, active
                """,
                (normalized,),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise ValueError(f"Unknown symbol: {normalized}")
    return dict(row)


def list_instruments(database_url: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            sql = """
                SELECT id, symbol, exchange, name, provider, active, created_at, updated_at
                FROM instruments
            """
            if active_only:
                sql += " WHERE active = true"
            sql += " ORDER BY symbol, exchange"
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]


def upsert_instrument(
    symbol: str,
    exchange: str,
    name: str,
    provider: str,
    database_url: str | None = None,
) -> dict[str, Any]:
    normalized_symbol = symbol.strip().upper()
    normalized_exchange = exchange.strip().upper()
    clean_name = (name or normalized_symbol).strip()
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO instruments(symbol, exchange, name, provider, active)
                VALUES (%s, %s, %s, %s, true)
                ON CONFLICT (symbol, exchange) DO UPDATE
                SET name = EXCLUDED.name,
                    provider = EXCLUDED.provider,
                    active = true,
                    updated_at = now()
                RETURNING id, symbol, exchange, name, provider, active
                """,
                (normalized_symbol, normalized_exchange, clean_name, provider),
            )
            row = dict(cur.fetchone())
            cur.execute(
                """
                INSERT INTO sync_status(instrument_id) VALUES (%s)
                ON CONFLICT (instrument_id) DO NOTHING
                """,
                (row["id"],),
            )
        conn.commit()
    return row


def deactivate_instrument(symbol: str, database_url: str | None = None) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE instruments
                SET active = false, updated_at = now()
                WHERE symbol = %s AND active = true
                RETURNING id, symbol, exchange, name, provider, active
                """,
                (normalized,),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise ValueError(f"Unknown or inactive symbol: {normalized}")
    return dict(row)

def upsert_daily_candles(
    instrument_id: int,
    candles: list[dict],
    provider: str,
    database_url: str | None = None,
) -> dict[str, int]:
    if not candles:
        return {"received": 0, "inserted": 0, "updated": 0}

    trade_dates = [date.fromisoformat(row["date"]) for row in candles]

    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date
                FROM daily_candles
                WHERE instrument_id = %s AND trade_date = ANY(%s)
                """,
                (instrument_id, trade_dates),
            )
            existing = {row["trade_date"] for row in cur.fetchall()}

            params = [
                (
                    instrument_id,
                    date.fromisoformat(row["date"]),
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row.get("volume", 0),
                    provider,
                )
                for row in candles
            ]
            cur.executemany(
                """
                INSERT INTO daily_candles(
                    instrument_id, trade_date, open, high, low, close, volume, provider
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (instrument_id, trade_date) DO UPDATE
                SET open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    provider = EXCLUDED.provider,
                    updated_at = now()
                """,
                params,
            )

        conn.commit()

    updated = sum(1 for d in trade_dates if d in existing)
    inserted = len(trade_dates) - updated
    return {"received": len(candles), "inserted": inserted, "updated": updated}


def mark_sync_success(
    instrument_id: int,
    last_sync_date: str | None,
    database_url: str | None = None,
) -> None:
    sync_date = date.fromisoformat(last_sync_date) if last_sync_date else None
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_status(
                    instrument_id, last_sync_date, status, error_count,
                    last_error, last_attempt_at, last_success_at, updated_at
                )
                VALUES (%s, %s, 'ok', 0, NULL, now(), now(), now())
                ON CONFLICT (instrument_id) DO UPDATE
                SET last_sync_date = EXCLUDED.last_sync_date,
                    status = 'ok',
                    error_count = 0,
                    last_error = NULL,
                    last_attempt_at = now(),
                    last_success_at = now(),
                    updated_at = now()
                """,
                (instrument_id, sync_date),
            )
        conn.commit()


def mark_sync_error(
    instrument_id: int,
    error: str,
    database_url: str | None = None,
) -> None:
    message = (error or "unknown error")[:2000]
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_status(
                    instrument_id, status, error_count, last_error,
                    last_attempt_at, updated_at
                )
                VALUES (%s, 'error', 1, %s, now(), now())
                ON CONFLICT (instrument_id) DO UPDATE
                SET status = 'error',
                    error_count = sync_status.error_count + 1,
                    last_error = EXCLUDED.last_error,
                    last_attempt_at = now(),
                    updated_at = now()
                """,
                (instrument_id, message),
            )
        conn.commit()



def candle_coverage(instrument_id: int, database_url: str | None = None) -> dict[str, Any]:
    """Return persisted D1 coverage for one instrument."""
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)::int AS count,
                       MIN(trade_date) AS first_date,
                       MAX(trade_date) AS last_date
                FROM daily_candles
                WHERE instrument_id = %s
                """,
                (instrument_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else {"count": 0, "first_date": None, "last_date": None}


def candle_stats(symbols: Iterable[str] | None = None, database_url: str | None = None) -> list[dict[str, Any]]:
    requested = [s.strip().upper() for s in (symbols or []) if s and s.strip()]
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            sql = """
                SELECT i.symbol,
                       COUNT(c.id)::int AS count,
                       MIN(c.trade_date) AS first_date,
                       MAX(c.trade_date) AS last_date
                FROM instruments i
                LEFT JOIN daily_candles c ON c.instrument_id = i.id
                WHERE i.active = true
            """
            params: tuple[Any, ...] = ()
            if requested:
                sql += " AND i.symbol = ANY(%s)"
                params = (requested,)
            sql += " GROUP BY i.id, i.symbol ORDER BY i.symbol"
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def get_daily_candles(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 300,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Read persisted D1 candles for one active instrument, oldest -> newest."""
    normalized = symbol.strip().upper()
    if limit < 1:
        raise ValueError("limit must be >= 1")

    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    if start_date and end_date and start_date > end_date:
        raise ValueError("start must be on or before end")

    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM instruments
                WHERE active = true AND symbol = %s
                ORDER BY id
                LIMIT 1
                """,
                (normalized,),
            )
            instrument = cur.fetchone()
            if not instrument:
                raise ValueError(f"Unknown or inactive symbol: {normalized}")

            sql = """
                SELECT trade_date, open, high, low, close, volume
                FROM daily_candles
                WHERE instrument_id = %s
            """
            params: list[Any] = [instrument["id"]]
            if start_date is not None:
                sql += " AND trade_date >= %s"
                params.append(start_date)
            if end_date is not None:
                sql += " AND trade_date <= %s"
                params.append(end_date)
            sql += " ORDER BY trade_date DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, tuple(params))
            rows = list(reversed(cur.fetchall()))

    return [
        {
            "date": row["trade_date"].isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for row in rows
    ]


def get_instrument_candles_with_provider(
    instrument_id: int,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Read all persisted candles for corporate-action rebuild planning."""
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, open, high, low, close, volume, provider
                FROM daily_candles
                WHERE instrument_id = %s
                ORDER BY trade_date
                """,
                (instrument_id,),
            )
            rows = cur.fetchall()
    return [
        {
            "date": row["trade_date"].isoformat(),
            "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
            "volume": float(row["volume"]), "provider": str(row.get("provider") or ""),
        }
        for row in rows
    ]




def get_processed_corporate_action_events(
    instrument_id: int,
    start: str | None = None,
    end: str | None = None,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Return SSI corporate-action events already reconciled for an instrument."""
    clauses = ["instrument_id = %s"]
    params: list[Any] = [instrument_id]
    if start:
        clauses.append("event_date >= %s")
        params.append(date.fromisoformat(start))
    if end:
        clauses.append("event_date <= %s")
        params.append(date.fromisoformat(end))

    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT instrument_id, event_date, previous_factor, new_factor,
                       ratio_change_pct, source, reconciliation_updated,
                       reconciliation_inserted, processed_at
                FROM corporate_action_events
                WHERE {' AND '.join(clauses)}
                ORDER BY event_date
                """,
                params,
            )
            rows = cur.fetchall()
    return [
        {
            **dict(row),
            "event_date": row["event_date"].isoformat(),
            "previous_factor": float(row["previous_factor"]) if row["previous_factor"] is not None else None,
            "new_factor": float(row["new_factor"]) if row["new_factor"] is not None else None,
            "ratio_change_pct": float(row["ratio_change_pct"]) if row["ratio_change_pct"] is not None else None,
        }
        for row in rows
    ]


def processed_corporate_action_dates(
    instrument_id: int,
    start: str | None = None,
    end: str | None = None,
    database_url: str | None = None,
) -> set[str]:
    return {
        row["event_date"]
        for row in get_processed_corporate_action_events(
            instrument_id, start=start, end=end, database_url=database_url
        )
    }


def apply_corporate_action_reconciliation(
    instrument_id: int,
    updates: list[dict[str, Any]],
    inserts: list[dict[str, Any]],
    provider: str = "ssi",
    database_url: str | None = None,
    processed_events: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Apply an SSI historical reconciliation in one transaction.

    Existing candle volume is preserved on UPDATE because this repair only
    reconciles adjusted OHLC. New sessions use SSI volume. No persisted row is
    deleted. The caller must build/validate the plan before invoking this.
    """
    processed_events = processed_events or []
    if not updates and not inserts and not processed_events:
        return {"updated": 0, "inserted": 0, "events_recorded": 0}

    with connect(database_url) as conn:
        with conn.cursor() as cur:
            updated = 0
            inserted = 0

            for row in updates:
                cur.execute(
                    """
                    UPDATE daily_candles
                    SET open = %s, high = %s, low = %s, close = %s,
                        provider = %s, updated_at = now()
                    WHERE instrument_id = %s AND trade_date = %s
                    """,
                    (
                        row["open"], row["high"], row["low"], row["close"],
                        provider, instrument_id, date.fromisoformat(row["date"]),
                    ),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"Corporate-action reconciliation expected one existing row for {row['date']}, got {cur.rowcount}"
                    )
                updated += 1

            for row in inserts:
                cur.execute(
                    """
                    INSERT INTO daily_candles(
                        instrument_id, trade_date, open, high, low, close, volume, provider
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (instrument_id, trade_date) DO NOTHING
                    """,
                    (
                        instrument_id, date.fromisoformat(row["date"]),
                        row["open"], row["high"], row["low"], row["close"],
                        row.get("volume", 0), provider,
                    ),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"Corporate-action reconciliation expected one new row for {row['date']}, got {cur.rowcount}"
                    )
                inserted += 1

            events_recorded = 0
            for event in processed_events:
                cur.execute(
                    """
                    INSERT INTO corporate_action_events(
                        instrument_id, event_date, previous_factor, new_factor,
                        ratio_change_pct, source, reconciliation_updated,
                        reconciliation_inserted, processed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (instrument_id, event_date) DO UPDATE
                    SET previous_factor = EXCLUDED.previous_factor,
                        new_factor = EXCLUDED.new_factor,
                        ratio_change_pct = EXCLUDED.ratio_change_pct,
                        source = EXCLUDED.source,
                        reconciliation_updated = EXCLUDED.reconciliation_updated,
                        reconciliation_inserted = EXCLUDED.reconciliation_inserted,
                        processed_at = now()
                    """,
                    (
                        instrument_id,
                        date.fromisoformat(str(event["event_date"])[:10]),
                        event.get("previous_factor"),
                        event.get("new_factor"),
                        event.get("ratio_change_pct"),
                        event.get("source", provider),
                        updated,
                        inserted,
                    ),
                )
                events_recorded += 1

        conn.commit()

    return {"updated": updated, "inserted": inserted, "events_recorded": events_recorded}


# Backward-compatible alias for dev scripts that may still import the old name.
def apply_corporate_action_updates(
    instrument_id: int,
    updates: list[dict[str, Any]],
    provider: str = "ssi",
    database_url: str | None = None,
) -> int:
    result = apply_corporate_action_reconciliation(
        instrument_id=instrument_id,
        updates=updates,
        inserts=[],
        provider=provider,
        database_url=database_url,
    )
    return result["updated"]
