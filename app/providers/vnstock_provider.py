from __future__ import annotations

from datetime import date, timedelta
import logging
import os
import time
from typing import Any

from .base import StockProvider
from ..normalize import normalize_ohlcv_rows


logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


class VnstockProvider(StockProvider):
    """Vnstock Community v4 provider using the Unified UI.

    Long history is fetched in small calendar chunks because Community may cap
    historical responses at roughly 100 rows. The provider also throttles
    requests proactively and retries rate-limit errors automatically so a
    multi-symbol backfill can finish unattended on the Guest tier.
    """

    # 120 calendar days is normally <100 Vietnamese trading sessions, so a
    # provider-side 100-row cap cannot silently truncate the middle of a chunk.
    HISTORY_CHUNK_DAYS = 120

    def __init__(
        self,
        source: str = "vnstock",
        requests_per_minute: int | None = None,
        retry_wait_seconds: int | None = None,
        max_rate_limit_retries: int | None = None,
    ):
        self.name = "vnstock"
        self.requests_per_minute = requests_per_minute or _env_int(
            "VNSTOCK_REQUESTS_PER_MINUTE", 8
        )
        self.retry_wait_seconds = retry_wait_seconds or _env_int(
            "VNSTOCK_RATE_LIMIT_RETRY_SECONDS", 70
        )
        self.max_rate_limit_retries = (
            max_rate_limit_retries
            if max_rate_limit_retries is not None
            else _env_int("VNSTOCK_RATE_LIMIT_MAX_RETRIES", 5, minimum=0)
        )
        self._min_request_interval = 60.0 / self.requests_per_minute
        self._last_request_at: float | None = None

    @staticmethod
    def _market():
        try:
            # Current Vnstock v4 PyPI public API.
            from vnstock import Market
        except ImportError:
            try:
                # Compatibility with documentation/builds exposing ui.Market.
                from vnstock.ui import Market
            except ImportError as exc:
                raise RuntimeError(
                    "vnstock Community is not installed. Run: pip install -U vnstock"
                ) from exc
        return Market()

    @staticmethod
    def _records(frame: Any) -> list[dict]:
        if frame is None:
            return []
        if hasattr(frame, "to_dict"):
            return frame.to_dict(orient="records")
        if isinstance(frame, list):
            return frame
        raise RuntimeError(f"Unsupported Vnstock response type: {type(frame).__name__}")

    @classmethod
    def _fetch_ohlcv(cls, symbol: str, start_date: str, end_date: str):
        market = cls._market()

        # Vnstock 4.0.x public examples use market.equity.ohlcv(symbol=...).
        equity = getattr(market, "equity", None)
        if equity is None:
            raise RuntimeError("Vnstock Market.equity API is unavailable")

        if hasattr(equity, "ohlcv"):
            return equity.ohlcv(
                symbol=symbol,
                start=start_date,
                end=end_date,
                interval="1D",
            )

        # Compatibility with builds/docs where equity is callable:
        # Market().equity("FPT").ohlcv(...)
        if callable(equity):
            instrument = equity(symbol)
            if hasattr(instrument, "ohlcv"):
                return instrument.ohlcv(
                    start=start_date,
                    end=end_date,
                    interval="1D",
                )

        raise RuntimeError("Unsupported Vnstock v4 equity OHLCV interface")

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc).lower()
        markers = (
            "rate limit",
            "rate-limit",
            "too many request",
            "too many requests",
            "429",
            "giới hạn api",
            "gioi han api",
            "maximum api request",
            "request limit",
        )
        return any(marker in text for marker in markers)

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            wait = self._min_request_interval - elapsed
            if wait > 0:
                logger.info("Vnstock throttle: waiting %.1fs", wait)
                time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _fetch_ohlcv_with_retry(self, symbol: str, start_date: str, end_date: str):
        attempt = 0
        while True:
            self._throttle()
            try:
                frame = self._fetch_ohlcv(symbol, start_date, end_date)
                records = self._records(frame)

                # Vnstock Community may print a rate-limit warning and return an
                # empty result instead of raising. A 120-day historical chunk
                # should contain trading sessions, except for genuinely future
                # ranges. Treat an empty completed historical chunk as a
                # transient upstream/quota failure and retry after cooldown.
                chunk_end = date.fromisoformat(end_date)
                if not records and chunk_end < date.today():
                    if attempt >= self.max_rate_limit_retries:
                        raise RuntimeError(
                            f"Vnstock returned empty historical data for {symbol} "
                            f"({start_date}..{end_date}) after retries"
                        )
                    attempt += 1
                    logger.warning(
                        "Vnstock returned empty historical chunk for %s (%s..%s). "
                        "Assuming quota/upstream issue; waiting %ss before retry %s/%s.",
                        symbol,
                        start_date,
                        end_date,
                        self.retry_wait_seconds,
                        attempt,
                        self.max_rate_limit_retries,
                    )
                    time.sleep(self.retry_wait_seconds)
                    self._last_request_at = None
                    continue

                return records
            except Exception as exc:
                if not self._is_rate_limit_error(exc) or attempt >= self.max_rate_limit_retries:
                    raise
                attempt += 1
                logger.warning(
                    "Vnstock rate limit for %s (%s..%s). Waiting %ss before retry %s/%s.",
                    symbol,
                    start_date,
                    end_date,
                    self.retry_wait_seconds,
                    attempt,
                    self.max_rate_limit_retries,
                )
                time.sleep(self.retry_wait_seconds)
                self._last_request_at = None

    @staticmethod
    def _default_start(end_day: date, limit: int) -> date:
        # VN equities trade about 5/7 calendar days, with additional holidays.
        # 2.2x provides comfortable headroom for long backfills.
        return end_day - timedelta(days=max(int(limit * 2.2), 400))

    def _fetch_chunked(
        self,
        symbol: str,
        start_day: date,
        end_day: date,
        limit: int,
    ) -> list[dict]:
        if start_day > end_day:
            raise ValueError("start must be on or before end")

        merged: dict[str, dict] = {}
        cursor_end = end_day
        total_days = (end_day - start_day).days + 1
        total_chunks = max(1, (total_days + self.HISTORY_CHUNK_DAYS - 1) // self.HISTORY_CHUNK_DAYS)
        chunk_no = 0

        # Walk backwards so callers asking only for the most recent N candles
        # can stop as soon as enough unique sessions have been collected.
        while cursor_end >= start_day and len(merged) < limit:
            chunk_no += 1
            cursor_start = max(
                start_day,
                cursor_end - timedelta(days=self.HISTORY_CHUNK_DAYS - 1),
            )
            logger.info(
                "%s: chunk %s/%s %s..%s (collected=%s/%s)",
                symbol,
                chunk_no,
                total_chunks,
                cursor_start.isoformat(),
                cursor_end.isoformat(),
                len(merged),
                limit,
            )

            records = self._fetch_ohlcv_with_retry(
                symbol,
                cursor_start.isoformat(),
                cursor_end.isoformat(),
            )
            rows = normalize_ohlcv_rows(records)
            for row in rows:
                merged[row["date"]] = row

            if cursor_start == start_day:
                break
            cursor_end = cursor_start - timedelta(days=1)

        return [merged[key] for key in sorted(merged)]

    def daily_ohlcv(
        self,
        symbol: str,
        start: str | None,
        end: str | None,
        limit: int,
    ) -> list[dict]:
        try:
            end_day = date.fromisoformat(end) if end else date.today()
            start_day = (
                date.fromisoformat(start)
                if start
                else self._default_start(end_day, limit)
            )
        except ValueError as exc:
            raise ValueError("start/end must use YYYY-MM-DD format") from exc

        rows = self._fetch_chunked(symbol, start_day, end_day, limit)
        return rows[-limit:]

    @staticmethod
    def _reference():
        try:
            from vnstock import Reference
        except ImportError:
            try:
                from vnstock.ui import Reference
            except ImportError as exc:
                raise RuntimeError(
                    "vnstock Community Reference API is unavailable. Run: pip install -U vnstock"
                ) from exc
        return Reference()

    @classmethod
    def _fetch_security_list(cls):
        ref = cls._reference()
        equity = getattr(ref, "equity", None)
        if equity is None:
            raise RuntimeError("Vnstock Reference.equity API is unavailable")
        if hasattr(equity, "list"):
            return equity.list()
        raise RuntimeError("Unsupported Vnstock v4 equity reference interface")

    def find_security(self, symbol: str) -> dict[str, str] | None:
        target = symbol.strip().upper()
        self._throttle()
        frame = self._fetch_security_list()
        rows = self._records(frame)
        for row in rows:
            lowered = {str(k).lower(): v for k, v in row.items()}
            row_symbol = str(
                lowered.get("symbol")
                or lowered.get("ticker")
                or lowered.get("code")
                or ""
            ).upper()
            if row_symbol != target:
                continue
            raw_exchange = str(
                lowered.get("exchange")
                or lowered.get("market")
                or lowered.get("comgroupcode")
                or ""
            ).upper()
            aliases = {"HSX": "HOSE", "HO": "HOSE", "UPCOM": "UPCOM", "HNX": "HNX"}
            exchange = aliases.get(raw_exchange, raw_exchange)
            name = str(
                lowered.get("organ_name")
                or lowered.get("organname")
                or lowered.get("company_name")
                or lowered.get("companyname")
                or lowered.get("name")
                or target
            ).strip()
            return {"symbol": target, "exchange": exchange, "name": name}
        return None
