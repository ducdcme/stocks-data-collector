from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from app.corporate_action import (
    build_factor_segments,
    build_reconciliation_plan,
    detect_factor_transitions,
    verify_requested_event_dates,
)
from app.providers.ssi_provider import SSIProvider
from app.repository import (
    apply_corporate_action_reconciliation,
    get_instrument,
    get_instrument_candles_with_provider,
)


def _limit(start: str, end: str) -> int:
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return max(300, min(5000, int(days * 5 / 7) + 120))


def _detect_events(
    ssi: SSIProvider,
    symbol: str,
    market: str,
    start: str,
    end: str,
    tolerance: float,
) -> dict:
    factors = ssi.daily_adjustment_factors(symbol, market, start, end)
    segments = build_factor_segments(factors, tolerance)
    transitions = detect_factor_transitions(segments, tolerance)
    likely = [row for row in transitions if row.likely_corporate_action]
    return {
        "window": {"start": start, "end": end},
        "segments": [row.__dict__ for row in segments],
        "transitions": [row.__dict__ for row in transitions],
        "likely_event_dates": [row.detected_from_date for row in likely],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Detect SSI corporate-action adjustment changes and reconcile PostgreSQL "
            "against current SSI DailyOhlc. SSI performs the adjustment; SDC only syncs the result."
        )
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--event-date",
        action="append",
        default=[],
        help=(
            "Expected event YYYY-MM-DD; may be supplied multiple times. "
            "The date is NEVER trusted by itself: SSI factor detection must confirm it."
        ),
    )
    parser.add_argument("--detect-start", help="Detection window start YYYY-MM-DD")
    parser.add_argument("--detect-end", help="Detection window end YYYY-MM-DD")
    parser.add_argument(
        "--detect-days",
        type=int,
        default=45,
        help="When no explicit detection range is supplied, inspect this many calendar days ending at DB latest date (default 45)",
    )
    parser.add_argument("--factor-tolerance", type=float, default=0.0005)
    parser.add_argument(
        "--price-tolerance",
        type=float,
        default=0.05,
        help="Material OHLC difference in thousand VND; default 0.05 = 50 VND",
    )
    parser.add_argument(
        "--history-start",
        help="Optional reconciliation start YYYY-MM-DD. Default: first persisted candle.",
    )
    parser.add_argument("--apply", action="store_true", help="Write reconciliation when safety checks pass")
    parser.add_argument("--force", action="store_true", help="Required together with --apply")
    parser.add_argument("--output-dir", default="adjustment_results")
    args = parser.parse_args()

    if args.detect_days < 2:
        parser.error("--detect-days must be >= 2")
    if args.price_tolerance < 0:
        parser.error("--price-tolerance must be >= 0")

    symbol = args.symbol.strip().upper()
    instrument = get_instrument(symbol)
    if not instrument or not instrument.get("active"):
        raise SystemExit(f"{symbol} must exist and be active before corporate-action processing")

    db_rows_all = get_instrument_candles_with_provider(instrument["id"])
    if not db_rows_all:
        raise SystemExit(f"{symbol} has no persisted candles")

    db_start = db_rows_all[0]["date"]
    db_end = db_rows_all[-1]["date"]
    history_start = args.history_start or db_start
    if date.fromisoformat(history_start) > date.fromisoformat(db_end):
        parser.error("--history-start must be on or before the latest DB candle")
    db_rows = [row for row in db_rows_all if row["date"] >= history_start]

    ssi = SSIProvider()
    if not ssi.configured:
        raise SystemExit("SSI credentials are required")

    requested_events = sorted(set(args.event_date))

    # Event dates supplied on the command line are expectations, not authority.
    # SSI DailyStockPrice must independently confirm a factor transition.
    if args.detect_start:
        detect_start = args.detect_start
    elif requested_events:
        detect_start = (
            date.fromisoformat(requested_events[0]) - timedelta(days=21)
        ).isoformat()
    else:
        detect_end_for_default = args.detect_end or db_end
        detect_start = (
            date.fromisoformat(detect_end_for_default)
            - timedelta(days=args.detect_days - 1)
        ).isoformat()

    if args.detect_end:
        detect_end = args.detect_end
    elif requested_events:
        detect_end = min(
            date.fromisoformat(db_end),
            date.fromisoformat(requested_events[-1]) + timedelta(days=21),
        ).isoformat()
    else:
        detect_end = db_end

    if date.fromisoformat(detect_start) > date.fromisoformat(detect_end):
        parser.error("detection start must be on or before detection end")

    detection = _detect_events(
        ssi,
        symbol,
        instrument["exchange"],
        detect_start,
        detect_end,
        args.factor_tolerance,
    )
    detection["mode"] = "ssi_factor_detection"

    verification = verify_requested_event_dates(
        requested_events, detection["likely_event_dates"]
    ) if requested_events else {
        "requested_event_dates": [],
        "detected_event_dates": detection["likely_event_dates"],
        "matched_event_dates": detection["likely_event_dates"],
        "missing_requested_event_dates": [],
        "unexpected_detected_event_dates": [],
        "verified": bool(detection["likely_event_dates"]),
    }
    detection["verification"] = verification

    if not detection["likely_event_dates"]:
        print(
            f"{symbol}: no likely SSI adjustment-factor transition in "
            f"{detect_start}..{detect_end}; no historical reconciliation needed"
        )
        return 0

    if requested_events and not verification["verified"]:
        print(
            f"{symbol}: SSI event verification FAILED · "
            f"requested={','.join(requested_events)} · "
            f"detected={','.join(detection['likely_event_dates']) or '-'} · "
            f"missing={','.join(verification['missing_requested_event_dates']) or '-'}"
        )

    print(
        f"{symbol}: SSI detected event(s)={','.join(detection['likely_event_dates'])} · "
        f"verified={detection['verification']['verified']} · "
        f"reconcile SSI DailyOhlc {history_start}..{db_end}"
    )
    if requested_events:
        print(
            f"event verification: requested={','.join(requested_events)} "
            f"matched={','.join(detection['verification']['matched_event_dates']) or '-'} "
            f"missing={','.join(detection['verification']['missing_requested_event_dates']) or '-'}"
        )

    ssi_rows = ssi.daily_ohlcv(
        symbol,
        history_start,
        db_end,
        _limit(history_start, db_end),
    )
    plan = build_reconciliation_plan(db_rows, ssi_rows, args.price_tolerance)

    event_verified = bool(detection["verification"]["verified"])
    write_safe = bool(plan["safe_to_apply"] and event_verified)

    payload = {
        "symbol": symbol,
        "exchange": instrument["exchange"],
        "detection": detection,
        "reconciliation_range": {"start": history_start, "end": db_end},
        "plan": plan,
        "write_gate": {
            "event_verified_by_ssi": event_verified,
            "reconciliation_safe": bool(plan["safe_to_apply"]),
            "safe_to_apply": write_safe,
        },
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = detection["likely_event_dates"][-1] if detection["likely_event_dates"] else "detected"
    output = output_dir / f"{symbol}_{suffix}_ssi_reconciliation.json"
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"SSI reconciliation: DB={plan['db_sessions']} SSI={plan['ssi_sessions']} "
        f"common={plan['common_sessions']} updates={plan['updates_count']} "
        f"inserts={plan['inserts_count']} unchanged={plan['unchanged_count']}"
    )
    print(
        f"coverage: missing_in_ssi={len(plan['missing_in_ssi'])} "
        f"missing_in_db={len(plan['missing_in_db'])} "
        f"safety={plan['safety']} reconciliation_safe={plan['safe_to_apply']}"
    )
    print(
        f"write gate: event_verified_by_ssi={event_verified} "
        f"safe_to_apply={write_safe}"
    )
    print(f"audit plan: {output}")

    if args.apply:
        if not args.force:
            raise SystemExit("Refusing write: --apply also requires --force")
        if not event_verified:
            missing = detection["verification"].get("missing_requested_event_dates") or []
            detail = ",".join(missing) if missing else "no SSI-confirmed event"
            raise SystemExit(
                f"Refusing write: corporate-action event was not verified by SSI ({detail})"
            )
        if not plan["safe_to_apply"]:
            raise SystemExit(f"Refusing write: reconciliation safety gate is {plan['safety']}")
        transition_by_date = {
            row["detected_from_date"]: row
            for row in detection["transitions"]
            if row.get("likely_corporate_action")
        }
        processed_events = []
        for event_date in detection["verification"]["matched_event_dates"]:
            transition = transition_by_date[event_date]
            processed_events.append(
                {
                    "event_date": event_date,
                    "previous_factor": transition["previous_factor"],
                    "new_factor": transition["new_factor"],
                    "ratio_change_pct": transition["ratio_change_pct"],
                    "source": "ssi",
                }
            )
        counts = apply_corporate_action_reconciliation(
            instrument_id=instrument["id"],
            updates=plan["updates"],
            inserts=plan["inserts"],
            provider="ssi",
            processed_events=processed_events,
        )
        print(
            f"APPLIED transactionally: updated={counts['updated']} inserted={counts['inserted']} "
            f"events_recorded={counts.get('events_recorded', 0)}"
        )
        print("Re-run the same command in dry-run mode; expected result is updates=0 inserts=0.")
    else:
        print("DRY RUN: PostgreSQL was not modified")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
