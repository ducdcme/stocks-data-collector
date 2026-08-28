from __future__ import annotations

import argparse

from app.repository import get_active_instruments, get_processed_corporate_action_events


def main() -> int:
    parser = argparse.ArgumentParser(description="List processed SSI corporate-action events")
    parser.add_argument("--symbols", nargs="+", help="Symbols to inspect (default: all active)")
    parser.add_argument("--start", help="Optional YYYY-MM-DD lower bound")
    parser.add_argument("--end", help="Optional YYYY-MM-DD upper bound")
    args = parser.parse_args()

    instruments = get_active_instruments(args.symbols)
    total = 0
    for instrument in instruments:
        rows = get_processed_corporate_action_events(
            instrument["id"], start=args.start, end=args.end
        )
        if not rows:
            print(f"{instrument['symbol']}: no processed corporate-action events")
            continue
        for row in rows:
            total += 1
            print(
                f"{instrument['symbol']}: event={row['event_date']} "
                f"factor={row['previous_factor']}->{row['new_factor']} "
                f"updated={row['reconciliation_updated']} inserted={row['reconciliation_inserted']} "
                f"processed_at={row['processed_at']}"
            )
    print(f"total events: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
