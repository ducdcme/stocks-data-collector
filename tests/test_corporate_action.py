from app.corporate_action import (
    build_factor_segments,
    build_reconciliation_plan,
    detect_factor_transitions,
)


def test_detects_transition_to_one():
    rows = [
        {"date": "2026-08-06", "factor": 0.833},
        {"date": "2026-08-07", "factor": 0.833},
        {"date": "2026-08-10", "factor": 0.833},
        {"date": "2026-08-11", "factor": 1.0},
        {"date": "2026-08-12", "factor": 1.0},
    ]
    transitions = detect_factor_transitions(build_factor_segments(rows))
    assert transitions[0].detected_from_date == "2026-08-11"
    assert transitions[0].likely_corporate_action is True


def test_supports_multiple_corporate_actions():
    rows = [
        {"date": "2026-05-04", "factor": 0.812634},
        {"date": "2026-05-25", "factor": 0.812634},
        {"date": "2026-05-26", "factor": 0.833300},
        {"date": "2026-06-09", "factor": 0.833300},
        {"date": "2026-06-10", "factor": 1.0},
    ]
    transitions = detect_factor_transitions(build_factor_segments(rows))
    assert [x.detected_from_date for x in transitions] == ["2026-05-26", "2026-06-10"]
    assert all(x.likely_corporate_action for x in transitions)


def candle(day, value, volume=100):
    return {
        "date": day,
        "open": value,
        "high": value + 1,
        "low": value - 1,
        "close": value + 0.2,
        "volume": volume,
    }


def test_reconciliation_updates_only_changed_ohlc():
    db = [candle("2026-08-07", 24), candle("2026-08-08", 20)]
    ssi = [candle("2026-08-07", 20), candle("2026-08-08", 20)]
    plan = build_reconciliation_plan(db, ssi)
    assert plan["safety"] == "ready_to_reconcile"
    assert plan["safe_to_apply"] is True
    assert plan["updates_count"] == 1
    assert plan["updates"][0]["date"] == "2026-08-07"
    assert plan["inserts"] == []


def test_reconciliation_is_idempotent_when_db_matches_ssi():
    rows = [candle("2026-08-07", 20), candle("2026-08-08", 21)]
    plan = build_reconciliation_plan(rows, rows)
    assert plan["safety"] == "already_in_sync"
    assert plan["safe_to_apply"] is True
    assert plan["updates_count"] == 0
    assert plan["inserts_count"] == 0


def test_reconciliation_inserts_missing_db_session():
    db = [candle("2026-08-07", 20)]
    ssi = [candle("2026-08-07", 20), candle("2026-08-08", 21, volume=777)]
    plan = build_reconciliation_plan(db, ssi)
    assert plan["safe_to_apply"] is True
    assert plan["inserts_count"] == 1
    assert plan["inserts"][0]["date"] == "2026-08-08"
    assert plan["inserts"][0]["volume"] == 777.0


def test_missing_persisted_session_in_ssi_blocks_apply_and_never_deletes():
    db = [candle("2026-08-07", 20), candle("2026-08-08", 21)]
    ssi = [candle("2026-08-07", 20)]
    plan = build_reconciliation_plan(db, ssi)
    assert plan["safe_to_apply"] is False
    assert plan["safety"] == "ssi_history_missing_persisted_dates"
    assert plan["missing_in_ssi"] == ["2026-08-08"]
    assert plan["updates"] == []
    assert plan["inserts"] == []


def test_tolerance_ignores_small_provider_rounding_difference():
    db = [candle("2026-08-07", 20.000)]
    ssi = [candle("2026-08-07", 20.020)]
    plan = build_reconciliation_plan(db, ssi, tolerance=0.05)
    assert plan["updates_count"] == 0
    assert plan["safety"] == "already_in_sync"


def test_requested_event_dates_must_match_ssi_detection():
    from app.corporate_action import verify_requested_event_dates

    result = verify_requested_event_dates(
        ["2026-05-26", "2026-06-10"],
        ["2026-05-26", "2026-06-10"],
    )
    assert result["verified"] is True
    assert result["matched_event_dates"] == ["2026-05-26", "2026-06-10"]
    assert result["missing_requested_event_dates"] == []


def test_requested_event_verification_fails_when_ssi_does_not_confirm_one_date():
    from app.corporate_action import verify_requested_event_dates

    result = verify_requested_event_dates(
        ["2026-05-26", "2026-06-10"],
        ["2026-06-10"],
    )
    assert result["verified"] is False
    assert result["matched_event_dates"] == ["2026-06-10"]
    assert result["missing_requested_event_dates"] == ["2026-05-26"]
