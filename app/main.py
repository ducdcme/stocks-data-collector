from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from datetime import date
import logging
from pydantic import BaseModel, Field

from . import __version__
from .config import settings
from .db import ping as db_ping
from .providers.vnstock_provider import VnstockProvider
from .providers.ssi_provider import SSIProvider
from .repository import (
    activate_instrument,
    candle_coverage,
    get_daily_candles,
    get_instrument,
    list_instruments,
    upsert_instrument,
    deactivate_instrument,
)
from .daily_sync import completed_market_date, sync_daily
from .backfill import backfill_symbols
from .catalog import SecurityCatalog
from .service import StockDataService
from .symbols import normalize_symbol, test_symbol_rows
from .universe import StockUniverseService

logger = logging.getLogger(__name__)


def _build_provider(name: str):
    normalized = (name or "").strip().lower()
    if normalized in ("vnstock", "community"):
        return VnstockProvider()
    if normalized == "ssi":
        provider = SSIProvider()
        if not provider.configured:
            raise RuntimeError("SSI provider selected but SSI_CONSUMER_ID/SSI_CONSUMER_SECRET are not configured")
        return provider
    raise RuntimeError(f"Unsupported stock provider: {name!r}")


def build_default_service() -> StockDataService:
    requested = [settings.primary_provider]
    if settings.fallback_provider and settings.fallback_provider != settings.primary_provider:
        requested.append(settings.fallback_provider)

    providers = []
    errors = []
    for index, name in enumerate(requested):
        try:
            provider = _build_provider(name)
            providers.append(provider)
        except RuntimeError as exc:
            errors.append(f"{name}: {exc}")
            if index == 0 and len(requested) > 1:
                logger.warning("Primary stock provider %s unavailable: %s; trying fallback %s", name, exc, requested[1])
            else:
                logger.warning("Stock provider %s unavailable: %s", name, exc)

    if not providers:
        raise RuntimeError("No stock provider is available: " + " | ".join(errors))
    logger.info("Stock providers active: %s", " -> ".join(provider.name for provider in providers))
    return StockDataService(providers)


service = build_default_service()

def build_catalog() -> SecurityCatalog:
    providers = []
    ssi = SSIProvider()
    if ssi.configured:
        providers.append(ssi)
    providers.append(VnstockProvider())
    return SecurityCatalog(providers)

catalog = build_catalog()
universe = StockUniverseService(SSIProvider())

class InstrumentCreate(BaseModel):
    symbol: str
    years: int = Field(default=3, ge=1, le=10)

app = FastAPI(title="VN Stocks Data Collector", version=__version__)


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": "VN Stocks Data Collector",
        "version": __version__,
        "providers": [provider.name for provider in service.providers],
        "database": {"configured": settings.database_enabled},
    }


@app.get("/health/db")
def health_db():
    if not settings.database_enabled:
        raise HTTPException(status_code=503, detail="STOCKS_DATABASE_URL is not configured")
    try:
        info = db_ping()
        return {"ok": True, **info}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@app.get("/symbols")
def symbols():
    if settings.database_enabled:
        rows = list_instruments(active_only=True)
        return {
            "symbols": [
                {
                    "symbol": row["symbol"],
                    "exchange": row["exchange"],
                    "name": row["name"],
                    "provider": row["provider"],
                }
                for row in rows
            ],
            "scope": "DATABASE_ACTIVE",
        }
    return {"symbols": test_symbol_rows(), "scope": "DEV1_TEST_SET"}


@app.get("/universe/groups")
def universe_groups():
    if not settings.database_enabled:
        raise HTTPException(status_code=503, detail="STOCKS_DATABASE_URL is not configured")
    try:
        return {"groups": universe.groups()}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/universe/{group}")
def universe_group(group: str):
    if not settings.database_enabled:
        raise HTTPException(status_code=503, detail="STOCKS_DATABASE_URL is not configured")
    try:
        return universe.group(group).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/admin/instruments")
def admin_add_instrument(request: InstrumentCreate):
    if not settings.database_enabled:
        raise HTTPException(status_code=503, detail="STOCKS_DATABASE_URL is not configured")

    # Production policy (preserves the dev architecture):
    # - active = managed/visible only; never a readiness/freshness flag.
    # - candle_count > 0 means chartable.
    # - candle_count >= STOCKS_MIN_PREPARED_CANDLES means signal-ready only.
    # - provider calls are skipped ONLY when persisted D1 data is current through
    #   the latest completed market date. Historical sync_status/error flags must
    #   never override the actual candle coverage in PostgreSQL.
    # - only new/empty symbols bootstrap history; existing stale symbols use
    #   Daily Sync so only the newer edge is fetched.
    try:
        normalized = normalize_symbol(request.symbol)
        existing = get_instrument(normalized)
        is_new = existing is None

        if existing is None:
            info = catalog.find(normalized)
            instrument = upsert_instrument(
                info.symbol, info.exchange, info.name, info.provider
            )
        else:
            instrument = existing
            if not instrument.get("active"):
                instrument = activate_instrument(normalized)

        coverage = candle_coverage(instrument["id"])
        count = int(coverage.get("count") or 0)
        first = coverage.get("first_date")
        last = coverage.get("last_date")
        if isinstance(last, str):
            last_date = date.fromisoformat(last)
        else:
            last_date = last

        target = completed_market_date()
        min_signal_candles = getattr(settings, "min_prepared_candles", 100)

        # Bootstrap is determined only by actual persisted data. A previous
        # sync_status=error is diagnostic state, not a reason to refetch history.
        # If candles exist, freshness is decided exclusively by MAX(trade_date).
        needs_backfill = is_new or count == 0

        if needs_backfill:
            results = backfill_symbols(
                service, symbols=[normalized], years=request.years, end_day=target
            )
            operation = "backfill"
            result = results[0] if results else None
            provider = result.provider if result else instrument.get("provider") or "database"
            fetched = result.fetched if result else 0
            inserted = result.inserted if result else 0
            updated = result.updated if result else 0
            skipped = bool(result.skipped) if result else False
        elif last_date is not None and last_date >= target:
            # DB is current. Do not touch SSI/Vnstock merely because the user
            # re-submitted the symbol or because it has fewer than 100 candles.
            logger.info(
                "ADD STOCK DB-FIRST symbol=%s candles=%s last=%s target=%s current=true; provider calls skipped",
                normalized, count, last_date, target,
            )
            operation = "current"
            provider = "database"
            fetched = inserted = updated = 0
            skipped = True
        else:
            # Existing bootstrap is healthy but stale: only fetch the missing
            # newer edge. This is the same freshness rule as scheduled Daily Sync.
            results = sync_daily(
                service, symbols=[normalized], as_of=target
            )
            operation = "sync"
            result = results[0] if results else None
            provider = result.provider if result else instrument.get("provider") or "database"
            fetched = result.fetched if result else 0
            inserted = result.inserted if result else 0
            updated = result.updated if result else 0
            skipped = bool(result.skipped) if result else False

        final_coverage = candle_coverage(instrument["id"])
        final_count = int(final_coverage.get("count") or 0)
        final_first = final_coverage.get("first_date")
        final_last = final_coverage.get("last_date")

        return {
            "ok": True,
            "instrument": {
                "symbol": instrument["symbol"],
                "exchange": instrument["exchange"],
                "name": instrument["name"],
                "provider": instrument["provider"],
                "active": True,
            },
            "backfill": {
                "symbol": normalized,
                "operation": operation,
                "provider": provider,
                "target_date": target.isoformat(),
                "fetched": fetched,
                "inserted": inserted,
                "updated": updated,
                "first_date": str(final_first) if final_first else None,
                "last_date": str(final_last) if final_last else None,
                "skipped": skipped,
                "candle_count": final_count,
                "chartable": final_count > 0,
                "ready_for_signal": final_count >= min_signal_candles,
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Never deactivate here. Instrument visibility and existing candles are
        # preserved; sync_status carries the retry/error state instead.
        logger.error("ADD STOCK FAILED symbol=%s reason=%s; keeping instrument active", request.symbol, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/admin/instruments/{symbol}")
def admin_remove_instrument(symbol: str):
    if not settings.database_enabled:
        raise HTTPException(status_code=503, detail="STOCKS_DATABASE_URL is not configured")
    try:
        row = deactivate_instrument(normalize_symbol(symbol))
        return {
            "ok": True,
            "instrument": {
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "name": row["name"],
                "provider": row["provider"],
                "active": row["active"],
            },
            "historyPreserved": True,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/candles/d1")
def candles_d1(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(default=settings.default_limit, ge=20, le=settings.max_limit),
):
    try:
        normalized = normalize_symbol(symbol)
        if settings.database_enabled:
            rows = get_daily_candles(normalized, start, end, limit)
            return {
                "symbol": normalized,
                "timeframe": "1D",
                "provider": "database",
                "count": len(rows),
                "candles": rows,
            }

        result = service.daily_ohlcv(normalized, start, end, limit)
        return {
            "symbol": normalized,
            "timeframe": "1D",
            "provider": result.provider,
            "count": len(result.candles),
            "candles": result.candles,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/admin/sync/daily")
def admin_sync_daily(symbols: str | None = None):
    if not settings.database_enabled:
        raise HTTPException(status_code=503, detail="STOCKS_DATABASE_URL is not configured")
    requested = [item.strip().upper() for item in symbols.split(",") if item.strip()] if symbols else None
    try:
        results = sync_daily(service, symbols=requested)
        return {
            "ok": True,
            "results": [result.__dict__ for result in results],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
