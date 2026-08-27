from __future__ import annotations

import argparse
import logging
from datetime import date

from app.daily_sync import completed_market_date, sync_daily
from app.db import ping
from app.main import build_default_service
from app.repository import candle_stats


def parse_args():
    parser = argparse.ArgumentParser(description="Sync new completed VN stock D1 candles into PostgreSQL")
    parser.add_argument("--symbols", nargs="+", help="Symbols to sync (default: all active instruments)")
    parser.add_argument("--as-of", help="Override completed market date (YYYY-MM-DD), mainly for testing/repair")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    args = parse_args()
    as_of = date.fromisoformat(args.as_of) if args.as_of else completed_market_date()
    symbols = [s.upper() for s in args.symbols] if args.symbols else None

    info = ping()
    print(f"database ok: {info.get('database')}")
    print(f"sync completed candles through: {as_of}")

    results = sync_daily(
        build_default_service(),
        symbols=symbols,
        as_of=as_of,
        progress=print,
    )
    for result in results:
        status = "SKIPPED" if result.skipped else "OK"
        extra = f" reason={result.reason}" if result.reason else ""
        print(
            f"{result.symbol}: {status} fetched={result.fetched} inserted={result.inserted} "
            f"updated={result.updated} request={result.start}..{result.end} "
            f"provider={result.provider}{extra}"
        )

    print("database stats:")
    for row in candle_stats(symbols):
        print(f"{row['symbol']}: count={row['count']} range={row['first_date']}..{row['last_date']}")


if __name__ == "__main__":
    main()
