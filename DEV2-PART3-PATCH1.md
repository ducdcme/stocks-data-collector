# Stocks Data Collector v0.2.0-dev.2 Patch 1

## Changes
- Default provider order is now `SSI -> VNSTOCK`.
- `.env` is loaded automatically via `python-dotenv`.
- Existing OS environment variables have priority over `.env` (`override=False`).
- `.env.example` contains the full local configuration template.
- `.gitignore` excludes `.env` and local Python artifacts.
- Provider logs now show primary/fallback selection, success, and fallback events.
- If SSI is configured as primary but credentials are missing, startup can still use the configured Vnstock fallback instead of crashing.

## Windows local setup
Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in at least:

```env
STOCKS_DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/stocks_data
SSI_CONSUMER_ID=YOUR_CONSUMER_ID
SSI_CONSUMER_SECRET=YOUR_CONSUMER_SECRET
```

Then start without `$env:` commands:

```powershell
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
```

Check:

```powershell
curl.exe http://127.0.0.1:8790/health
```

Expected provider order:

```json
"providers": ["ssi", "vnstock"]
```

Daily sync also reads `.env` automatically:

```powershell
python -m scripts.sync_daily
```
