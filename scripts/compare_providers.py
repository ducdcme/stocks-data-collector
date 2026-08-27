from __future__ import annotations

import argparse
from datetime import date, timedelta

from app.providers.ssi_provider import SSIProvider
from app.providers.vnstock_provider import VnstockProvider


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Vnstock and SSI D1 OHLCV")
    parser.add_argument("--symbols", nargs="+", default=["FPT", "HPG"])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--price-tolerance", type=float, default=0.02, help="thousand VND")
    args = parser.parse_args()

    ssi = SSIProvider()
    if not ssi.configured:
        raise SystemExit("Set SSI_CONSUMER_ID and SSI_CONSUMER_SECRET first")
    vn = VnstockProvider()
    end = date.today()
    start = end - timedelta(days=max(args.days, 7))

    for symbol in [s.upper() for s in args.symbols]:
        vr = vn.daily_ohlcv(symbol, start.isoformat(), end.isoformat(), 100)
        sr = ssi.daily_ohlcv(symbol, start.isoformat(), end.isoformat(), 100)
        vm = {r["date"]: r for r in vr}
        sm = {r["date"]: r for r in sr}
        common = sorted(set(vm) & set(sm))
        mismatches = []
        for day in common:
            diffs = {k: abs(vm[day][k] - sm[day][k]) for k in ("open", "high", "low", "close")}
            if max(diffs.values(), default=0) > args.price_tolerance:
                mismatches.append((day, diffs, vm[day], sm[day]))
        print(f"{symbol}: vnstock={len(vr)} ssi={len(sr)} common={len(common)} price_mismatches={len(mismatches)}")
        if common:
            day = common[-1]
            print(f"  latest common {day}: VNSTOCK={vm[day]} SSI={sm[day]}")
        if mismatches:
            day, diffs, _, _ = mismatches[-1]
            print(f"  latest mismatch {day}: {diffs}")


if __name__ == "__main__":
    main()
