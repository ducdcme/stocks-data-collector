from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.providers.ssi_provider import SSIProvider
from app.providers.vnstock_provider import VnstockProvider


def _limit(start: str, end: str) -> int:
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return max(300, min(5000, int(days * 5 / 7) + 120))


def _changed(a: dict[str, Any], b: dict[str, Any], tolerance: float) -> tuple[bool, dict[str, float]]:
    diffs = {key: abs(float(a[key]) - float(b[key])) for key in ("open", "high", "low", "close")}
    return max(diffs.values(), default=0.0) > tolerance, diffs


def compare_rows(
    ssi_rows: list[dict[str, Any]],
    vn_rows: list[dict[str, Any]],
    tolerance: float,
    event_date: str | None = None,
) -> dict[str, Any]:
    """Compare SSI DailyOhlc with VnStock OHLC on identical sessions.

    This intentionally compares provider histories directly, without using the
    local PostgreSQL contents.  It answers the question needed by the corporate
    action design: does SSI historical OHLC already converge to VnStock's
    adjusted analytical history after an event is known?
    """
    sm = {str(row["date"])[:10]: row for row in ssi_rows}
    vm = {str(row["date"])[:10]: row for row in vn_rows}
    common = sorted(set(sm) & set(vm))
    missing_ssi = sorted(set(vm) - set(sm))
    missing_vn = sorted(set(sm) - set(vm))
    event = date.fromisoformat(event_date) if event_date else None

    details: list[dict[str, Any]] = []
    for day in common:
        changed, diffs = _changed(sm[day], vm[day], tolerance)
        details.append(
            {
                "date": day,
                "before_event": bool(event and date.fromisoformat(day) < event),
                "changed": changed,
                "diffs": diffs,
                "ssi": {k: float(sm[day][k]) for k in ("open", "high", "low", "close")},
                "vnstock": {k: float(vm[day][k]) for k in ("open", "high", "low", "close")},
            }
        )

    if event:
        before = [row for row in details if row["before_event"]]
        after = [row for row in details if not row["before_event"]]
    else:
        before = []
        after = details

    def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
        changed = [row for row in rows if row["changed"]]
        return {
            "sessions": len(rows),
            "changed_sessions": len(changed),
            "changed_ratio": len(changed) / len(rows) if rows else 0.0,
            "max_abs_diff": max(
                (max(row["diffs"].values(), default=0.0) for row in rows),
                default=0.0,
            ),
        }

    return {
        "tolerance_thousand_vnd": tolerance,
        "event_date": event_date,
        "ssi_sessions": len(ssi_rows),
        "vnstock_sessions": len(vn_rows),
        "common_sessions": len(common),
        "missing_in_ssi": missing_ssi,
        "missing_in_vnstock": missing_vn,
        "before_event": stats(before),
        "on_or_after_event": stats(after),
        "overall": stats(details),
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare SSI DailyOhlc and VnStock historical OHLC directly, independent of PostgreSQL"
    )
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", help="YYYY-MM-DD")
    parser.add_argument("--end", help="YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=365, help="used when --start is omitted")
    parser.add_argument("--event-date", help="optional event YYYY-MM-DD; valid with a single symbol")
    parser.add_argument("--price-tolerance", type=float, default=0.05, help="thousand VND; default 0.05 = 50 VND")
    parser.add_argument("--output-dir", default="provider_comparison_results")
    args = parser.parse_args()

    if args.event_date and len(args.symbols) != 1:
        parser.error("--event-date can be used only with one symbol per command")
    if args.price_tolerance < 0:
        parser.error("--price-tolerance must be >= 0")

    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=max(args.days, 7))
    if start > end:
        parser.error("--start must be on or before --end")

    ssi = SSIProvider()
    if not ssi.configured:
        raise SystemExit("Set SSI_CONSUMER_ID and SSI_CONSUMER_SECRET first")
    vn = VnstockProvider()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for raw_symbol in args.symbols:
        symbol = raw_symbol.upper()
        sr = ssi.daily_ohlcv(symbol, start.isoformat(), end.isoformat(), _limit(start.isoformat(), end.isoformat()))
        vr = vn.daily_ohlcv(symbol, start.isoformat(), end.isoformat(), _limit(start.isoformat(), end.isoformat()))
        report = compare_rows(sr, vr, args.price_tolerance, args.event_date)
        report.update({"symbol": symbol, "start": start.isoformat(), "end": end.isoformat()})

        overall = report["overall"]
        print(
            f"{symbol}: SSI={report['ssi_sessions']} VNSTOCK={report['vnstock_sessions']} "
            f"common={report['common_sessions']} mismatches={overall['changed_sessions']}/{overall['sessions']} "
            f"({overall['changed_ratio']:.1%}) max_diff={overall['max_abs_diff']:.3f}"
        )
        if args.event_date:
            before = report["before_event"]
            after = report["on_or_after_event"]
            print(
                f"  before {args.event_date}: mismatch={before['changed_sessions']}/{before['sessions']} "
                f"({before['changed_ratio']:.1%}) max_diff={before['max_abs_diff']:.3f}"
            )
            print(
                f"  on/after {args.event_date}: mismatch={after['changed_sessions']}/{after['sessions']} "
                f"({after['changed_ratio']:.1%}) max_diff={after['max_abs_diff']:.3f}"
            )
        print(f"  missing: SSI={len(report['missing_in_ssi'])} VNSTOCK={len(report['missing_in_vnstock'])}")

        path = output_dir / f"{symbol}_{start.isoformat()}_{end.isoformat()}_ssi_vs_vnstock.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  report: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
