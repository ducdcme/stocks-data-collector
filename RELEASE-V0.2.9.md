# Stocks Data Collector v0.2.9

## SSI quota resilience

- Adds a process-wide SSI request gate (default 1.05 seconds between SSI HTTP calls) so concurrent provider operations respect the observed `maximum admitted 1 per 1s` quota.
- Retries SSI payload-level quota errors with bounded backoff before surfacing an error.
- Keeps transport retries for timeout/network failures and the v0.2.8 holiday-safe metadata fallbacks.
- If universe discovery still exhausts SSI quota after retries, `/universe/groups` falls back to last-known-good SSI cache or active PostgreSQL exchange membership instead of returning HTTP 502.
- Adds regression tests for quota retry, shared rate limiting, and universe fallback.

No database migration or dependency change is required. Existing `.env` files remain valid; new SSI tuning variables are optional.
