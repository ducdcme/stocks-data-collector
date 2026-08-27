from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Iterable

from .providers.base import StockProvider

logger = logging.getLogger(__name__)


@dataclass
class ProviderResult:
    provider: str
    candles: list[dict]


class StockDataService:
    def __init__(self, providers: Iterable[StockProvider]):
        self.providers = [p for p in providers]
        if not self.providers:
            raise ValueError("At least one stock provider is required")

    def daily_ohlcv(self, symbol: str, start: str | None, end: str | None, limit: int, empty_ok: bool = False) -> ProviderResult:
        errors: list[str] = []
        last_empty_provider: str | None = None
        for index, provider in enumerate(self.providers):
            role = "primary" if index == 0 else "fallback"
            logger.info(
                "%s: provider=%s role=%s request=%s..%s limit=%s",
                symbol, provider.name, role, start or "latest", end or "latest", limit,
            )
            try:
                rows = provider.daily_ohlcv(symbol, start, end, limit)
                if rows:
                    logger.info(
                        "%s: provider=%s role=%s success candles=%s range=%s..%s",
                        symbol, provider.name, role, len(rows), rows[0].get("date"), rows[-1].get("date"),
                    )
                    return ProviderResult(provider=provider.name, candles=rows)
                last_empty_provider = provider.name
                errors.append(f"{provider.name}: empty response")
                logger.warning("%s: provider=%s role=%s returned empty response", symbol, provider.name, role)
            except Exception as exc:  # provider isolation/fallback is intentional
                errors.append(f"{provider.name}: {exc}")
                if index + 1 < len(self.providers):
                    logger.warning(
                        "%s: provider=%s failed (%s); falling back to %s",
                        symbol, provider.name, exc, self.providers[index + 1].name,
                    )
                else:
                    logger.error("%s: provider=%s failed (%s)", symbol, provider.name, exc)
        if empty_ok and last_empty_provider is not None:
            return ProviderResult(provider=last_empty_provider, candles=[])
        raise RuntimeError("All stock providers failed: " + " | ".join(errors))
