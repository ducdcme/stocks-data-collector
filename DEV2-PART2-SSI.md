# Trading Signal v3.3.0 — DEV 2 / Part 2 — SSI Provider

## Goal
Add SSI FastConnect Data as a second upstream provider without replacing Vnstock yet.

## Provider policy for this step
- Primary: `vnstock`
- Fallback: `ssi` only after local SSI tests pass
- Comparison: run `scripts.compare_providers` for FPT/HPG before enabling fallback

## SSI REST credentials
FastConnect Data REST AccessToken uses:
- `SSI_CONSUMER_ID`
- `SSI_CONSUMER_SECRET`

`SSI_PUBLIC_KEY` and `SSI_PRIVATE_KEY` are accepted in config for future streaming/signature work, but are not used by the DailyOhlc REST test in this step.

## Windows local test
Set credentials in the current PowerShell session (do not commit them):

```powershell
$env:SSI_CONSUMER_ID="YOUR_NEW_CONSUMER_ID"
$env:SSI_CONSUMER_SECRET="YOUR_NEW_CONSUMER_SECRET"
```

Keep PostgreSQL config as before when running the full service:

```powershell
$env:STOCKS_DATABASE_URL="postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/stocks_data"
```

### 1. Test SSI auth + FPT DailyOhlc

```powershell
python -m scripts.test_ssi --symbol FPT --days 30
```

Expected:
- `SSI auth: PASS`
- count > 0
- latest OHLCV printed in the same **thousand VND** scale as Vnstock/Trading Signal

### 2. Compare SSI vs Vnstock

```powershell
python -m scripts.compare_providers --symbols FPT HPG --days 30
```

Expected:
- both providers return data
- common trading dates > 0
- OHLC values are close after SSI VND -> thousand VND normalization

Volume can differ slightly depending on upstream definitions/revisions; this step primarily validates OHLC and dates.

### Historical note: initial fallback test (superseded by Part 3 Patch 1)

```powershell
$env:STOCKS_PROVIDER_PRIMARY="ssi"
$env:STOCKS_PROVIDER_FALLBACK="vnstock"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
```

Check:

```powershell
curl.exe http://127.0.0.1:8790/health
```

Expected providers:

```json
["ssi", "vnstock"]
```

The database-backed `/candles/d1` API still reads PostgreSQL first, so enabling SSI fallback affects collector/backfill/daily-sync upstream behavior, not chart reads.

## Internal validation
- pytest: 30/30 PASS
- compileall: PASS
