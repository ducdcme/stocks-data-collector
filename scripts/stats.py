from __future__ import annotations

import argparse

from app.db import ping
from app.repository import candle_stats


def main():
    parser = argparse.ArgumentParser(description="Show D1 candle counts in PostgreSQL")
    parser.add_argument("--symbols", nargs="+")
    args = parser.parse_args()
    symbols = [s.upper() for s in args.symbols] if args.symbols else None

    info = ping()
    print(f"database ok: {info.get('database')}")
    for row in candle_stats(symbols):
        print(
            f"{row['symbol']}: count={row['count']} "
            f"range={row['first_date']}..{row['last_date']}"
        )


if __name__ == "__main__":
    main()
