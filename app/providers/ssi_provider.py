from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import os
import time
from typing import Any

import httpx

from .base import StockProvider

logger = logging.getLogger(__name__)


class SSIProvider(StockProvider):
    """SSI FastConnect Data REST provider.

    REST authentication uses ConsumerID + ConsumerSecret to obtain an access
    token. DailyOhlc returns prices in VND, while Trading Signal's existing VN
    stock pipeline stores prices in thousand VND, so prices are divided by 1000
    during normalization.
    """

    name = "ssi"
    DEFAULT_BASE_URL = "https://fc-data.ssi.com.vn/api/v2/Market"

    def __init__(
        self,
        consumer_id: str | None = None,
        consumer_secret: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
    ):
        self.consumer_id = (consumer_id or os.getenv("SSI_CONSUMER_ID", "")).strip()
        self.consumer_secret = (consumer_secret or os.getenv("SSI_CONSUMER_SECRET", "")).strip()
        self.base_url = (base_url or os.getenv("SSI_DATA_BASE_URL", self.DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout or float(os.getenv("SSI_REQUEST_TIMEOUT", "20"))
        # Reuse one HTTP client/connection pool for the lifetime of the provider.
        # Bulk imports otherwise create many TLS handshakes and are more prone to
        # intermittent SSI handshake/read timeouts.
        self._client = client or httpx.Client(timeout=self.timeout)
        self._access_token: str | None = None
        self._token_created_at: float | None = None
        self._token_ttl_seconds = int(os.getenv("SSI_TOKEN_CACHE_SECONDS", "1800"))
        self._request_retries = max(0, int(os.getenv("SSI_REQUEST_RETRIES", "2")))
        self._retry_delay_seconds = max(0.0, float(os.getenv("SSI_RETRY_DELAY_SECONDS", "1")))
        self._securities_cache_seconds = max(0, int(os.getenv("SSI_SECURITIES_CACHE_SECONDS", "300")))
        self._securities_cache: dict[str, tuple[float, list[dict]]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.consumer_id and self.consumer_secret)

    def _http(self) -> httpx.Client:
        return self._client

    def _retry_http(self, label: str, operation):
        """Retry transient network/timeout failures before provider fallback."""
        attempts = self._request_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                return operation()
            except httpx.TransportError as exc:
                if attempt >= attempts:
                    raise
                delay = self._retry_delay_seconds * attempt
                logger.warning(
                    "SSI %s transient failure (%s); retry %s/%s in %.1fs",
                    label, exc, attempt, self._request_retries, delay,
                )
                if delay:
                    time.sleep(delay)

    def _get_token(self, force: bool = False) -> str:
        if not self.configured:
            raise RuntimeError("SSI credentials are not configured")
        now = time.monotonic()
        if (
            not force
            and self._access_token
            and self._token_created_at is not None
            and now - self._token_created_at < self._token_ttl_seconds
        ):
            return self._access_token

        response = self._retry_http(
            "AccessToken",
            lambda: self._http().post(
                f"{self.base_url}/AccessToken",
                json={"consumerID": self.consumer_id, "consumerSecret": self.consumer_secret},
            ),
        )
        response.raise_for_status()
        payload = response.json()
        token = ((payload.get("data") or {}).get("accessToken") or "").strip()
        if not token:
            raise RuntimeError(f"SSI AccessToken failed: {payload.get('message') or payload.get('status') or 'missing token'}")
        self._access_token = token
        self._token_created_at = now
        return token

    @staticmethod
    def _ssi_date(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("SSI TradingDate is missing")
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text[:10], fmt).date().isoformat()
            except ValueError:
                pass
        raise ValueError(f"Unsupported SSI TradingDate: {text}")

    @classmethod
    def _normalize_rows(cls, rows: list[dict[str, Any]]) -> list[dict]:
        normalized: dict[str, dict] = {}
        for row in rows:
            day = cls._ssi_date(row.get("TradingDate") or row.get("tradingDate"))
            # SSI DailyOhlc examples are VND (e.g. 28,600); the existing DB/UI
            # contract uses thousand VND (e.g. 28.6).
            values = {
                "open": float(row.get("Open", 0)) / 1000.0,
                "high": float(row.get("High", 0)) / 1000.0,
                "low": float(row.get("Low", 0)) / 1000.0,
                "close": float(row.get("Close", 0)) / 1000.0,
                "volume": float(row.get("Volume") or 0),
            }
            if min(values["open"], values["high"], values["low"], values["close"]) <= 0:
                raise ValueError(f"Invalid SSI OHLC for {day}")
            if values["high"] < max(values["open"], values["close"], values["low"]):
                raise ValueError(f"SSI high is inconsistent for {day}")
            if values["low"] > min(values["open"], values["close"], values["high"]):
                raise ValueError(f"SSI low is inconsistent for {day}")
            normalized[day] = {"date": day, **values}
        return [normalized[key] for key in sorted(normalized)]

    def _get(self, path: str, params: dict[str, Any]) -> dict:
        token = self._get_token()
        response = self._retry_http(
            path,
            lambda: self._http().get(
                f"{self.base_url}/{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            ),
        )
        if response.status_code == 401:
            token = self._get_token(force=True)
            response = self._retry_http(
                path,
                lambda: self._http().get(
                    f"{self.base_url}/{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                ),
            )
        response.raise_for_status()
        payload = response.json()
        status = str(payload.get("status", "")).lower()
        if status not in ("success", "200", "") and not payload.get("data"):
            raise RuntimeError(f"SSI {path} failed: {payload.get('message') or payload.get('status')}")
        return payload

    def securities(self, market: str | None = None, page_size: int = 1000) -> list[dict]:
        cache_key = (market or "ALL").upper()
        now = time.monotonic()
        cached = self._securities_cache.get(cache_key)
        if cached and now - cached[0] < self._securities_cache_seconds:
            return list(cached[1])

        params = {"pageIndex": 1, "pageSize": page_size}
        if market:
            params["market"] = market.upper()
        payload = self._get("Securities", params)
        rows = list(payload.get("data") or [])
        if self._securities_cache_seconds:
            self._securities_cache[cache_key] = (now, rows)
        return list(rows)


    def index_components(self, index_code: str, page_size: int = 1000) -> list[str]:
        payload = self._get(
            "IndexComponents",
            {"indexCode": str(index_code).upper(), "pageIndex": 1, "pageSize": page_size},
        )
        symbols: list[str] = []
        for group in list(payload.get("data") or []):
            for row in list(group.get("IndexComponent") or group.get("indexComponent") or []):
                symbol = str(row.get("StockSymbol") or row.get("stockSymbol") or "").strip().upper()
                if symbol:
                    symbols.append(symbol)
        return sorted(set(symbols))

    def market_securities(self, market: str) -> list[dict[str, str]]:
        rows = self.securities(market=market, page_size=1000)
        out: list[dict[str, str]] = []
        for row in rows:
            symbol = str(row.get("Symbol") or row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            exchange = str(row.get("Market") or row.get("market") or market).strip().upper()
            name = str(row.get("StockName") or row.get("stockName") or row.get("StockEnName") or symbol).strip()
            out.append({"symbol": symbol, "exchange": exchange, "name": name})
        dedup = {row["symbol"]: row for row in out}
        return [dedup[key] for key in sorted(dedup)]

    def daily_ohlcv(self, symbol: str, start: str | None, end: str | None, limit: int) -> list[dict]:
        end_day = date.fromisoformat(end) if end else date.today()
        start_day = date.fromisoformat(start) if start else end_day - timedelta(days=max(limit * 2, 400))
        if start_day > end_day:
            raise ValueError("start must be on or before end")

        page_size = min(1000, max(10, limit))
        payload = self._get(
            "DailyOhlc",
            {
                "symbol": symbol.upper(),
                "fromDate": start_day.strftime("%d/%m/%Y"),
                "toDate": end_day.strftime("%d/%m/%Y"),
                "pageIndex": 1,
                "pageSize": page_size,
                "ascending": True,
            },
        )
        rows = self._normalize_rows(list(payload.get("data") or []))
        return rows[-limit:]

    def find_security(self, symbol: str) -> dict[str, str] | None:
        target = symbol.strip().upper()
        # Query each equity exchange separately so pageSize=1000 cannot hide
        # symbols when the all-market result grows beyond one page.
        for market in ("HOSE", "HNX", "UPCOM"):
            for row in self.securities(market=market, page_size=1000):
                row_symbol = str(row.get("Symbol") or row.get("symbol") or "").upper()
                if row_symbol != target:
                    continue
                return {
                    "symbol": target,
                    "exchange": str(row.get("Market") or row.get("market") or market).upper(),
                    "name": str(row.get("StockName") or row.get("stockName") or row.get("StockEnName") or target).strip(),
                }
        return None

    def daily_adjustment_factors(
        self,
        symbol: str,
        market: str,
        start: str,
        end: str,
        chunk_days: int = 20,
    ) -> list[dict[str, Any]]:
        """Read SSI DailyStockPrice and derive historical adjustment factors.

        SSI limits DailyStockPrice date windows to at most 30 calendar days,
        so this helper chunks longer ranges automatically and merges by date.
        It is used only to detect corporate-action factor regime changes;
        adjusted OHLC itself always comes from SSI DailyOhlc.
        """
        start_day = date.fromisoformat(start)
        end_day = date.fromisoformat(end)
        if start_day > end_day:
            raise ValueError("start must be on or before end")
        if chunk_days < 1 or chunk_days > 30:
            raise ValueError("chunk_days must be between 1 and 30")

        merged: dict[str, dict[str, Any]] = {}
        cursor = start_day
        while cursor <= end_day:
            chunk_end = min(end_day, cursor + timedelta(days=chunk_days - 1))
            payload = self._get(
                "DailyStockPrice",
                {
                    "symbol": symbol.upper(),
                    "market": market.upper(),
                    "fromDate": cursor.strftime("%d/%m/%Y"),
                    "toDate": chunk_end.strftime("%d/%m/%Y"),
                    "pageIndex": 1,
                    "pageSize": 1000,
                    "ascending": True,
                },
            )
            for row in list(payload.get("data") or []):
                raw = row.get("ClosePrice", row.get("closePrice"))
                adjusted = row.get("ClosePriceAdjusted", row.get("closePriceAdjusted"))
                if raw in (None, "", 0, "0") or adjusted in (None, ""):
                    continue
                raw_value = float(str(raw).replace(",", ""))
                adjusted_value = float(str(adjusted).replace(",", ""))
                if raw_value <= 0:
                    continue
                day = self._ssi_date(row.get("TradingDate") or row.get("tradingDate"))
                merged[day] = {
                    "date": day,
                    "raw_close": raw_value,
                    "adjusted_close": adjusted_value,
                    "factor": adjusted_value / raw_value,
                }
            cursor = chunk_end + timedelta(days=1)

        return [merged[key] for key in sorted(merged)]
