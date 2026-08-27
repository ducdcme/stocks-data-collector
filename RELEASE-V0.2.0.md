# VN Stocks Data Collector v0.2.0

Production companion service for Trading Signal v3.3.0.

- SSI FastConnect Data: primary.
- Vnstock Community: fallback.
- PostgreSQL database: `stocks_data`.
- D1 smart backfill and daily sync.
- Dynamic instruments and scanner-universe APIs.
- `.env` automatic loading; OS environment variables override `.env`.
- Final regression: 40/40 tests PASS; compileall PASS.
