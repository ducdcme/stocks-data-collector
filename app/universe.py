from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from .repository import list_instruments

GROUPS = ("VN30", "HOSE", "HNX", "UPCOM")


@dataclass
class UniverseGroup:
    group: str
    provider: str
    total: int
    prepared: list[dict[str, Any]]
    missing: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "provider": self.provider,
            "total": self.total,
            "preparedCount": len(self.prepared),
            "missingCount": len(self.missing),
            "prepared": self.prepared,
            "missing": self.missing,
        }


class StockUniverseService:
    """Resolve scanner groups without automatically backfilling the whole market.

    SSI is used only to discover group membership. A stock is scan-ready only if
    it is already active in PostgreSQL. This keeps scanning fast and prevents a
    click on HOSE/HNX/UPCOM from triggering hundreds of historical API calls.
    """

    def __init__(self, ssi_provider=None, ttl_seconds: int = 300):
        self.ssi = ssi_provider if getattr(ssi_provider, "configured", False) else None
        self.ttl_seconds = max(30, int(ttl_seconds))
        self._cache: dict[str, tuple[float, list[dict[str, str]]]] = {}

    def _active(self) -> list[dict[str, Any]]:
        return list_instruments(active_only=True)

    def _discover(self, group: str) -> tuple[str, list[dict[str, str]]]:
        normalized = str(group or "").strip().upper()
        if normalized not in GROUPS:
            raise ValueError(f"Unsupported stock scanner group: {normalized or 'empty'}")

        now = time.monotonic()
        cached = self._cache.get(normalized)
        if cached and now - cached[0] < self.ttl_seconds:
            return "ssi", cached[1]

        if self.ssi is None:
            rows = [
                {"symbol": row["symbol"], "exchange": row["exchange"], "name": row["name"]}
                for row in self._active()
                if normalized != "VN30" and row["exchange"] == normalized
            ]
            return "database", rows

        if normalized == "VN30":
            symbols = self.ssi.index_components("VN30", page_size=1000)
            # Securities metadata is useful in UI and also verifies current listing.
            by_symbol: dict[str, dict[str, str]] = {}
            for market in ("HOSE", "HNX"):
                for row in self.ssi.market_securities(market):
                    by_symbol[row["symbol"]] = row
            rows = [by_symbol.get(symbol, {"symbol": symbol, "exchange": "HOSE", "name": symbol}) for symbol in symbols]
        else:
            rows = self.ssi.market_securities(normalized)

        dedup = {row["symbol"]: row for row in rows if row.get("symbol")}
        resolved = [dedup[key] for key in sorted(dedup)]
        self._cache[normalized] = (now, resolved)
        return "ssi", resolved

    def group(self, group: str) -> UniverseGroup:
        normalized = str(group or "").strip().upper()
        provider, discovered = self._discover(normalized)
        active = {row["symbol"]: row for row in self._active()}
        discovered_symbols = [row["symbol"] for row in discovered]
        prepared = [
            {
                "symbol": active[symbol]["symbol"],
                "exchange": active[symbol]["exchange"],
                "name": active[symbol]["name"],
                "provider": active[symbol]["provider"],
            }
            for symbol in discovered_symbols
            if symbol in active
        ]
        missing = [symbol for symbol in discovered_symbols if symbol not in active]
        return UniverseGroup(normalized, provider, len(discovered_symbols), prepared, missing)

    def groups(self) -> list[dict[str, Any]]:
        return [self.group(group).as_dict() for group in GROUPS]
