from __future__ import annotations

import httpx

from app.providers.ssi_provider import SSIProvider


class FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, json):
        self.calls.append(("POST", url, json))
        return httpx.Response(200, json={"status": 200, "message": "Success", "data": {"accessToken": "abc"}}, request=httpx.Request("POST", url))

    def get(self, url, params, headers):
        self.calls.append(("GET", url, params, headers))
        return httpx.Response(200, json={"status": "Success", "message": "Success", "totalRecord": 2, "data": [
            {"Symbol":"FPT","Market":"HOSE","TradingDate":"24/08/2026","Open":"71000","High":"72000","Low":"70500","Close":"71800","Volume":"1000"},
            {"Symbol":"FPT","Market":"HOSE","TradingDate":"25/08/2026","Open":"71800","High":"73000","Low":"71500","Close":"72200","Volume":"2000"},
        ]}, request=httpx.Request("GET", url))


def test_ssi_auth_and_daily_normalization():
    client = FakeClient()
    p = SSIProvider(consumer_id="id", consumer_secret="secret", client=client)
    rows = p.daily_ohlcv("FPT", "2026-08-24", "2026-08-25", 10)
    assert rows[-1] == {"date":"2026-08-25","open":71.8,"high":73.0,"low":71.5,"close":72.2,"volume":2000.0}
    assert client.calls[0][0] == "POST"
    assert client.calls[0][2] == {"consumerID":"id","consumerSecret":"secret"}
    assert client.calls[1][3]["Authorization"] == "Bearer abc"
    assert client.calls[1][2]["fromDate"] == "24/08/2026"


def test_ssi_token_is_cached():
    client = FakeClient()
    p = SSIProvider(consumer_id="id", consumer_secret="secret", client=client)
    p.daily_ohlcv("FPT", "2026-08-24", "2026-08-25", 10)
    p.daily_ohlcv("HPG", "2026-08-24", "2026-08-25", 10)
    assert sum(1 for c in client.calls if c[0] == "POST") == 1

class IndexClient(FakeClient):
    def get(self, url, params, headers):
        self.calls.append(("GET", url, params, headers))
        if url.endswith("/IndexComponents"):
            payload = {"status":"Success","data":[{"IndexCode":"VN30","IndexComponent":[{"StockSymbol":"FPT"},{"StockSymbol":"MBB"}]}]}
        else:
            payload = {"status":"Success","data":[{"Symbol":"FPT","Market":"HOSE","StockName":"FPT Corp"}]}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


def test_ssi_index_components_and_market_securities():
    client = IndexClient()
    p = SSIProvider(consumer_id="id", consumer_secret="secret", client=client)
    assert p.index_components("VN30") == ["FPT", "MBB"]
    assert p.market_securities("HOSE") == [{"symbol":"FPT","exchange":"HOSE","name":"FPT Corp"}]

class FlakyClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.failures_left = 1

    def get(self, url, params, headers):
        self.calls.append(("GET", url, params, headers))
        if self.failures_left:
            self.failures_left -= 1
            raise httpx.ReadTimeout("temporary timeout", request=httpx.Request("GET", url))
        return httpx.Response(200, json={"status":"Success","data":[
            {"TradingDate":"25/08/2026","Open":"71800","High":"73000","Low":"71500","Close":"72200","Volume":"2000"}
        ]}, request=httpx.Request("GET", url))


def test_ssi_retries_transient_timeout(monkeypatch):
    monkeypatch.setenv("SSI_REQUEST_RETRIES", "2")
    monkeypatch.setenv("SSI_RETRY_DELAY_SECONDS", "0")
    client = FlakyClient()
    p = SSIProvider(consumer_id="id", consumer_secret="secret", client=client)
    rows = p.daily_ohlcv("FPT", "2026-08-25", "2026-08-25", 10)
    assert rows[-1]["close"] == 72.2
    assert sum(1 for c in client.calls if c[0] == "GET") == 2


class SecuritiesCacheClient(FakeClient):
    def get(self, url, params, headers):
        self.calls.append(("GET", url, params, headers))
        return httpx.Response(200, json={"status":"Success","data":[
            {"Symbol":"FPT","Market":"HOSE","StockName":"FPT Corp"},
            {"Symbol":"HPG","Market":"HOSE","StockName":"Hoa Phat Group"},
        ]}, request=httpx.Request("GET", url))


def test_ssi_securities_cache_reuses_market_lookup(monkeypatch):
    monkeypatch.setenv("SSI_SECURITIES_CACHE_SECONDS", "300")
    client = SecuritiesCacheClient()
    p = SSIProvider(consumer_id="id", consumer_secret="secret", client=client)
    assert p.find_security("FPT")["symbol"] == "FPT"
    assert p.find_security("HPG")["symbol"] == "HPG"
    securities_gets = [c for c in client.calls if c[0] == "GET" and c[1].endswith("/Securities")]
    assert len(securities_gets) == 1

class DailyStockPriceChunkClient(FakeClient):
    def get(self, url, params, headers):
        self.calls.append(("GET", url, params, headers))
        if url.endswith("/DailyStockPrice"):
            from_date = params["fromDate"]
            to_date = params["toDate"]
            payload = {
                "status": "Success",
                "data": [
                    {
                        "TradingDate": from_date,
                        "ClosePrice": "24000",
                        "ClosePriceAdjusted": "20000",
                    },
                    {
                        "TradingDate": to_date,
                        "ClosePrice": "20000",
                        "ClosePriceAdjusted": "20000",
                    },
                ],
            }
        else:
            payload = {"status": "Success", "data": []}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


def test_ssi_daily_adjustment_factors_chunks_long_ranges():
    client = DailyStockPriceChunkClient()
    p = SSIProvider(consumer_id="id", consumer_secret="secret", client=client)
    rows = p.daily_adjustment_factors(
        "MBB", "HOSE", "2026-07-01", "2026-08-27", chunk_days=20
    )
    gets = [c for c in client.calls if c[0] == "GET" and c[1].endswith("/DailyStockPrice")]
    assert len(gets) == 3
    assert gets[0][2]["fromDate"] == "01/07/2026"
    assert gets[0][2]["toDate"] == "20/07/2026"
    assert gets[-1][2]["fromDate"] == "10/08/2026"
    assert gets[-1][2]["toDate"] == "27/08/2026"
    assert rows[0]["factor"] == 20000 / 24000
    assert rows[-1]["factor"] == 1.0
