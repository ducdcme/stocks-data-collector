from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .symbols import normalize_symbol


@dataclass
class SecurityInfo:
    symbol: str
    exchange: str
    name: str
    provider: str


class SecurityCatalog:
    def __init__(self, providers: Iterable[Any]):
        self.providers = [p for p in providers]
        if not self.providers:
            raise ValueError("At least one catalog provider is required")

    def find(self, symbol: str) -> SecurityInfo:
        normalized = normalize_symbol(symbol)
        errors: list[str] = []
        for provider in self.providers:
            finder = getattr(provider, "find_security", None)
            if not callable(finder):
                continue
            try:
                row = finder(normalized)
                if row:
                    exchange = str(row.get("exchange") or row.get("market") or "").upper()
                    name = str(row.get("name") or row.get("stock_name") or normalized).strip()
                    if exchange not in {"HOSE", "HNX", "UPCOM"}:
                        raise ValueError(f"Unsupported exchange for {normalized}: {exchange or 'unknown'}")
                    return SecurityInfo(normalized, exchange, name, provider.name)
                errors.append(f"{provider.name}: symbol not found")
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
        raise ValueError(f"Không tìm thấy mã cổ phiếu {normalized}: " + " | ".join(errors))
