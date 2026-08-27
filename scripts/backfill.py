from __future__ import annotations

import argparse
import logging

from app.backfill import backfill_symbols
from app.db import ping
from app.main import build_default_service
from app.repository import candle_stats


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill VN stock D1 candles into PostgreSQL")
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Symbols to backfill (default: all active instruments)",
    )
    parser.add_argument("--years", type=int, default=3, help="History years (default: 3)")
    parser.add_argument("--force", action="store_true", help="Refetch the full requested range even when DB already has coverage")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    args = parse_args()
    if args.years < 1 or args.years > 6:
        raise SystemExit("--years must be between 1 and 6")

    info = ping()
    print(f"database ok: {info.get('database')}")
    service = build_default_service()
    symbols = [s.upper() for s in args.symbols] if args.symbols else None

    results = backfill_symbols(service, symbols=symbols, years=args.years, progress=print, force=args.force)
    for result in results:
        status = "SKIPPED " if result.skipped else ""
        print(
            f"{result.symbol}: {status}fetched={result.fetched} "
            f"inserted={result.inserted} updated={result.updated} "
            f"range={result.first_date}..{result.last_date} "
            f"provider={result.provider}"
        )

    print("database stats:")
    for row in candle_stats(symbols):
        print(
            f"{row['symbol']}: count={row['count']} "
            f"range={row['first_date']}..{row['last_date']}"
        )


if __name__ == "__main__":
    main()
