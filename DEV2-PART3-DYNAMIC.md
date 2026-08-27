# Stocks Data Collector v0.2.0-dev.2 — Dynamic Stock Universe

## Scope
- Dynamic active instrument list from PostgreSQL.
- Add a new VN equity without editing source code.
- Auto-resolve symbol, exchange, and company name.
- Automatically smart-backfill D1 history when a symbol is added.
- Remove = deactivate only; historical candles remain in PostgreSQL.

## Provider discovery
1. SSI Securities is preferred for reference lookup when SSI credentials are configured.
2. Vnstock Community Reference is the fallback lookup.
3. D1 backfill continues to use the configured market-data provider chain.

## API
- `GET /symbols` — active instruments from PostgreSQL.
- `POST /admin/instruments` body `{ "symbol": "VCB", "years": 3 }`.
- `DELETE /admin/instruments/VCB`.

## Windows local test
Set the same PostgreSQL and SSI environment values used in Part 2, then run:

```powershell
$env:STOCKS_DATABASE_URL="postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/stocks_data"
$env:SSI_CONSUMER_ID="YOUR_CONSUMER_ID"
$env:SSI_CONSUMER_SECRET="YOUR_CONSUMER_SECRET"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
```

Test adding one new symbol:

```powershell
curl.exe -X POST -H "Content-Type: application/json" -d '{"symbol":"VCB","years":3}' http://127.0.0.1:8790/admin/instruments
curl.exe http://127.0.0.1:8790/symbols
curl.exe "http://127.0.0.1:8790/candles/d1?symbol=VCB&limit=20"
```

Remove it without deleting history:

```powershell
curl.exe -X DELETE http://127.0.0.1:8790/admin/instruments/VCB
```

Re-adding VCB reactivates the existing instrument and Smart Backfill only fetches missing edge ranges.

## Internal validation
- `pytest`: 33/33 PASS
