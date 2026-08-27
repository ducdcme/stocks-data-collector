from __future__ import annotations

from datetime import date, datetime, timezone
from numbers import Number
from typing import Any, Iterable


def _pick(row: dict[str, Any], *names: str) -> Any:
    lowered = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Number):
        # pandas Timestamp.value may surface as ns. Epoch seconds/ms are also accepted.
        numeric = float(value)
        if numeric > 1e17:
            numeric /= 1e9
        elif numeric > 1e11:
            numeric /= 1e3
        return datetime.fromtimestamp(numeric, tz=timezone.utc).date().isoformat()
    text = str(value or "").strip()
    if not text:
        raise ValueError("Missing candle date")
    # Handles ISO timestamps while preserving the exchange-session calendar date.
    return text[:10]


def normalize_ohlcv_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    candles: list[dict[str, Any]] = []
    for raw in rows:
        day = _date_text(_pick(raw, "time", "date", "trading_date", "tradingdate"))
        values = {
            "open": float(_pick(raw, "open", "open_price")),
            "high": float(_pick(raw, "high", "high_price")),
            "low": float(_pick(raw, "low", "low_price")),
            "close": float(_pick(raw, "close", "close_price")),
        }
        if any(v <= 0 for v in values.values()):
            raise ValueError(f"Invalid OHLC for {day}")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError(f"High is inconsistent for {day}")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError(f"Low is inconsistent for {day}")
        volume_raw = _pick(raw, "volume", "match_volume", "total_volume")
        volume = float(volume_raw or 0)
        if volume < 0:
            raise ValueError(f"Invalid volume for {day}")
        candles.append({"date": day, **values, "volume": volume})

    candles.sort(key=lambda item: item["date"])
    # Last duplicate wins, which is useful when providers return a revised session row.
    deduped = {item["date"]: item for item in candles}
    return list(deduped.values())
