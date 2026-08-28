from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any


@dataclass
class AdjustmentSegment:
    start_date: str
    end_date: str
    factor: float
    sessions: int


@dataclass
class AdjustmentTransition:
    previous_segment_end: str
    detected_from_date: str
    previous_factor: float
    new_factor: float
    ratio_change_pct: float
    likely_corporate_action: bool


@dataclass
class ReconciliationDifference:
    date: str
    db_open: float | None
    db_high: float | None
    db_low: float | None
    db_close: float | None
    ssi_open: float
    ssi_high: float
    ssi_low: float
    ssi_close: float
    changed_open: bool
    changed_high: bool
    changed_low: bool
    changed_close: bool
    action: str

    @property
    def changed_any_ohlc(self) -> bool:
        return any((self.changed_open, self.changed_high, self.changed_low, self.changed_close))

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["changed_any_ohlc"] = self.changed_any_ohlc
        return row


def build_factor_segments(rows: list[dict[str, Any]], tolerance: float = 0.0005) -> list[AdjustmentSegment]:
    valid = [row for row in rows if row.get("factor") is not None]
    if not valid:
        return []

    segments: list[AdjustmentSegment] = []
    start = end = str(valid[0]["date"])
    values = [float(valid[0]["factor"])]

    for row in valid[1:]:
        current = mean(values)
        value = float(row["factor"])
        if abs(value - current) <= tolerance:
            end = str(row["date"])
            values.append(value)
            continue
        segments.append(AdjustmentSegment(start, end, mean(values), len(values)))
        start = end = str(row["date"])
        values = [value]

    segments.append(AdjustmentSegment(start, end, mean(values), len(values)))
    return segments


def detect_factor_transitions(
    segments: list[AdjustmentSegment], tolerance: float = 0.0005
) -> list[AdjustmentTransition]:
    out: list[AdjustmentTransition] = []
    for previous, current in zip(segments, segments[1:]):
        ratio = current.factor / previous.factor - 1.0 if previous.factor else 0.0
        materially_changed = abs(current.factor - previous.factor) > tolerance
        likely = materially_changed and (
            abs(current.factor - 1.0) <= max(tolerance * 2, 0.001)
            or abs(ratio) >= 0.01
        )
        out.append(
            AdjustmentTransition(
                previous_segment_end=previous.end_date,
                detected_from_date=current.start_date,
                previous_factor=previous.factor,
                new_factor=current.factor,
                ratio_change_pct=ratio * 100.0,
                likely_corporate_action=likely,
            )
        )
    return out



def verify_requested_event_dates(
    requested_dates: list[str],
    detected_dates: list[str],
) -> dict[str, Any]:
    """Verify user-supplied event dates against SSI-detected factor transitions.

    A requested date is only trusted when SSI independently reports a likely
    corporate-action factor transition on that exact trading date.  The caller
    can still run a dry-run when verification fails, but automatic/write mode
    must treat ``verified`` as a hard safety gate.
    """
    requested = sorted(set(str(day)[:10] for day in requested_dates))
    detected = sorted(set(str(day)[:10] for day in detected_dates))
    requested_set = set(requested)
    detected_set = set(detected)
    matched = sorted(requested_set & detected_set)
    missing = sorted(requested_set - detected_set)
    unexpected = sorted(detected_set - requested_set)
    return {
        "requested_event_dates": requested,
        "detected_event_dates": detected,
        "matched_event_dates": matched,
        "missing_requested_event_dates": missing,
        "unexpected_detected_event_dates": unexpected,
        "verified": bool(requested) and not missing,
    }

def build_reconciliation_plan(
    db_rows: list[dict[str, Any]],
    ssi_rows: list[dict[str, Any]],
    tolerance: float = 0.05,
) -> dict[str, Any]:
    """Plan an idempotent PostgreSQL reconciliation against SSI DailyOhlc.

    SSI is the canonical adjusted OHLC source. The collector does not calculate
    corporate-action prices itself. It only detects that SSI changed history,
    fetches the current SSI DailyOhlc series, and reconciles persisted candles.

    Existing rows are updated only when one or more OHLC fields differ beyond
    ``tolerance``. Missing DB sessions that exist in SSI are inserted. Existing
    DB sessions missing from SSI are never deleted and block automatic apply,
    because that usually indicates incomplete provider coverage or a bad range.

    Volume is deliberately preserved on UPDATE. For INSERT, SSI volume is used.
    """
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")

    db_map = {str(row["date"])[:10]: row for row in db_rows}
    ssi_map = {str(row["date"])[:10]: row for row in ssi_rows}

    common = sorted(set(db_map) & set(ssi_map))
    missing_in_ssi = sorted(set(db_map) - set(ssi_map))
    missing_in_db = sorted(set(ssi_map) - set(db_map))

    differences: list[ReconciliationDifference] = []
    updates: list[dict[str, Any]] = []
    inserts: list[dict[str, Any]] = []

    for day in common:
        old = db_map[day]
        new = ssi_map[day]
        changed = {
            key: abs(float(new[key]) - float(old[key])) > tolerance
            for key in ("open", "high", "low", "close")
        }
        action = "update" if any(changed.values()) else "skip"
        differences.append(
            ReconciliationDifference(
                date=day,
                db_open=float(old["open"]),
                db_high=float(old["high"]),
                db_low=float(old["low"]),
                db_close=float(old["close"]),
                ssi_open=float(new["open"]),
                ssi_high=float(new["high"]),
                ssi_low=float(new["low"]),
                ssi_close=float(new["close"]),
                changed_open=changed["open"],
                changed_high=changed["high"],
                changed_low=changed["low"],
                changed_close=changed["close"],
                action=action,
            )
        )
        if action == "update":
            updates.append(
                {
                    "date": day,
                    "open": float(new["open"]),
                    "high": float(new["high"]),
                    "low": float(new["low"]),
                    "close": float(new["close"]),
                }
            )

    for day in missing_in_db:
        row = ssi_map[day]
        inserts.append(
            {
                "date": day,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume") or 0),
            }
        )
        differences.append(
            ReconciliationDifference(
                date=day,
                db_open=None,
                db_high=None,
                db_low=None,
                db_close=None,
                ssi_open=float(row["open"]),
                ssi_high=float(row["high"]),
                ssi_low=float(row["low"]),
                ssi_close=float(row["close"]),
                changed_open=True,
                changed_high=True,
                changed_low=True,
                changed_close=True,
                action="insert",
            )
        )

    differences.sort(key=lambda row: row.date)
    safe_to_apply = not missing_in_ssi
    if missing_in_ssi:
        safety = "ssi_history_missing_persisted_dates"
    elif not updates and not inserts:
        safety = "already_in_sync"
    else:
        safety = "ready_to_reconcile"

    return {
        "canonical_source": "ssi_daily_ohlc",
        "tolerance_thousand_vnd": tolerance,
        "db_sessions": len(db_rows),
        "ssi_sessions": len(ssi_rows),
        "common_sessions": len(common),
        "missing_in_ssi": missing_in_ssi,
        "missing_in_db": missing_in_db,
        "updates_count": len(updates),
        "inserts_count": len(inserts),
        "unchanged_count": len(common) - len(updates),
        "safe_to_apply": safe_to_apply,
        "safety": safety,
        "updates": updates,
        "inserts": inserts,
        "differences": [row.as_dict() for row in differences],
    }
