from __future__ import annotations

import argparse
from datetime import date, timedelta

from app.providers.ssi_provider import SSIProvider


def main() -> None:
    parser = argparse.ArgumentParser(description="Test SSI FastConnect Data provider")
    parser.add_argument("--symbol", default="FPT")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    provider = SSIProvider()
    if not provider.configured:
        raise SystemExit("Set SSI_CONSUMER_ID and SSI_CONSUMER_SECRET first")
    end = date.today()
    start = end - timedelta(days=max(args.days, 7))
    rows = provider.daily_ohlcv(args.symbol, start.isoformat(), end.isoformat(), 100)
    print(f"SSI auth: PASS")
    print(f"symbol={args.symbol.upper()} count={len(rows)} range={rows[0]['date'] if rows else '-'}..{rows[-1]['date'] if rows else '-'}")
    if rows:
        print("latest:", rows[-1])


if __name__ == "__main__":
    main()
