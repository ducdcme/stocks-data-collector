from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any

from .repository import list_instruments

logger = logging.getLogger(__name__)

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

    SSI discovery endpoints can legitimately return ``There is no data`` during
    Vietnamese market holidays / non-trading periods. That condition must not
    make the whole scanner fail. We prefer the last successful SSI discovery
    cache; if none exists, exchange groups fall back to active PostgreSQL rows.
    VN30 cannot be reconstructed safely from exchange alone, so without a cached
    SSI membership it is returned as unavailable/empty instead of inventing
    constituents or failing ``/universe/groups`` for every scan scope.
    """

    def __init__(self, ssi_provider=None, ttl_seconds: int = 300):
        self.ssi = ssi_provider if getattr(ssi_provider, "configured", False) else None
        self.ttl_seconds = max(30, int(ttl_seconds))
        # Keep expired entries: they are intentionally useful as a last-known-good
        # membership snapshot when SSI says "There is no data" on a holiday.
        self._cache: dict[str, tuple[float, list[dict[str, str]]]] = {}

    def _active(self) -> list[dict[str, Any]]:
        return list_instruments(active_only=True)

    @staticmethod
    def _is_no_data_error(exc: Exception) -> bool:
        return "there is no data" in str(exc).strip().lower()

    def _database_fallback(
        self,
        group: str,
        *,
        provider: str = "database-fallback",
    ) -> tuple[str, list[dict[str, str]]]:
        if group == "VN30":
            # PostgreSQL stores exchange metadata, not index membership. Returning
            # HOSE as VN30 would silently scan the wrong universe.
            return provider, []
        rows = [
            {"symbol": row["symbol"], "exchange": row["exchange"], "name": row["name"]}
            for row in self._active()
            if row["exchange"] == group
        ]
        rows.sort(key=lambda row: row["symbol"])
        return provider, rows

    def _holiday_fallback(
        self,
        group: str,
        cached: tuple[float, list[dict[str, str]]] | None,
        exc: RuntimeError,
    ) -> tuple[str, list[dict[str, str]]]:
        if cached is not None:
            logger.warning(
                "SSI universe %s returned no data; using last successful SSI cache (%s rows)",
                group,
                len(cached[1]),
            )
            return "ssi-cache", list(cached[1])

        provider, rows = self._database_fallback(group)
        logger.warning(
            "SSI universe %s returned no data and no SSI cache is available; using %s (%s rows): %s",
            group,
            provider,
            len(rows),
            exc,
        )
        return provider, rows

    def _discover(self, group: str) -> tuple[str, list[dict[str, str]]]:
        normalized = str(group or "").strip().upper()
        if normalized not in GROUPS:
            raise ValueError(f"Unsupported stock scanner group: {normalized or 'empty'}")

        now = time.monotonic()
        cached = self._cache.get(normalized)
        if cached and now - cached[0] < self.ttl_seconds:
            return "ssi", list(cached[1])

        if self.ssi is None:
            return self._database_fallback(normalized, provider="database")

        try:
            if normalized == "VN30":
                symbols = self.ssi.index_components("VN30", page_size=1000)
                # Securities metadata is useful in UI and also verifies current listing.
                by_symbol: dict[str, dict[str, str]] = {}
                for market in ("HOSE", "HNX"):
                    for row in self.ssi.market_securities(market):
                        by_symbol[row["symbol"]] = row
                rows = [
                    by_symbol.get(symbol, {"symbol": symbol, "exchange": "HOSE", "name": symbol})
                    for symbol in symbols
                ]
            else:
                rows = self.ssi.market_securities(normalized)
        except RuntimeError as exc:
            if self._is_no_data_error(exc):
                return self._holiday_fallback(normalized, cached, exc)
            raise

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
