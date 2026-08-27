from __future__ import annotations

from abc import ABC, abstractmethod


class StockProvider(ABC):
    name: str

    @abstractmethod
    def daily_ohlcv(self, symbol: str, start: str | None, end: str | None, limit: int) -> list[dict]:
        raise NotImplementedError
