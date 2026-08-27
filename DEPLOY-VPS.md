# Deploy VN Stocks Data Collector v0.2.0 on Ubuntu VPS

Recommended layout:

```text
/opt/stocks-data-collector
/opt/stocks-data-collector/.venv
/etc/stocks-data-collector.env
PostgreSQL DB: stocks_data
HTTP: 127.0.0.1:8790
```

## 1. PostgreSQL

Create a dedicated DB/user (names may be adjusted to your server policy):

```sql
CREATE USER stockscollector WITH PASSWORD 'CHANGE_ME';
CREATE DATABASE stocks_data OWNER stockscollector;
```

## 2. Install/update source

```bash
sudo mkdir -p /opt/stocks-data-collector
sudo chown -R $USER:$USER /opt/stocks-data-collector
cd /opt/stocks-data-collector
# clone the repository on first install, or git pull on updates
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 3. Environment file

Create `/etc/stocks-data-collector.env`:

```env
STOCKS_HOST=127.0.0.1
STOCKS_PORT=8790
STOCKS_DATABASE_URL=postgresql://stockscollector:CHANGE_ME@127.0.0.1:5432/stocks_data
STOCKS_PROVIDER_PRIMARY=ssi
STOCKS_PROVIDER_FALLBACK=vnstock
SSI_CONSUMER_ID=...
SSI_CONSUMER_SECRET=...
SSI_PUBLIC_KEY=
SSI_PRIVATE_KEY=
```

Protect it:

```bash
sudo chmod 600 /etc/stocks-data-collector.env
```

## 4. Migration

```bash
cd /opt/stocks-data-collector
set -a
source /etc/stocks-data-collector.env
set +a
. .venv/bin/activate
python -m scripts.migrate
```

## 5. systemd

Create `/etc/systemd/system/stocks-data-collector.service`:

```ini
[Unit]
Description=VN Stocks Data Collector
After=network.target postgresql.service

[Service]
Type=simple
WorkingDirectory=/opt/stocks-data-collector
EnvironmentFile=/etc/stocks-data-collector.env
ExecStart=/opt/stocks-data-collector/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now stocks-data-collector
sudo systemctl status stocks-data-collector
curl http://127.0.0.1:8790/health
```

## 6. Initial preparation
Use Trading Signal UI to add/backfill the stock lists you actually need. Scanner runs remain DB-only.


## Upgrade v0.2.0 -> v0.2.1 (copy deployment)

No database migration is required.

1. Stop the service:

```bash
sudo systemctl stop stocks-data-collector
```

2. Back up the current source (do not copy `.venv` or production env into the backup package):

```bash
cp -a /opt/stocks-data-collector /opt/stocks-data-collector-v0.2.0-backup
```

3. Copy the v0.2.1 source contents into `/opt/stocks-data-collector`, preserving `/opt/stocks-data-collector/.venv`.

4. Ensure ownership remains:

```bash
chown -R stockscollector:stockscollector /opt/stocks-data-collector
```

5. Optional but recommended production settings in `/etc/stocks-data-collector.env`:

```env
SSI_REQUEST_RETRIES=2
SSI_RETRY_DELAY_SECONDS=1
SSI_SECURITIES_CACHE_SECONDS=300
```

6. Reinstall requirements only if the package file changed (v0.2.1 adds no new dependency):

```bash
sudo -u stockscollector /opt/stocks-data-collector/.venv/bin/pip install -r /opt/stocks-data-collector/requirements.txt
```

7. Start and verify:

```bash
sudo systemctl start stocks-data-collector
curl http://127.0.0.1:8790/health
journalctl -u stocks-data-collector -n 50 --no-pager
```

`/health` must report version `0.2.1`.

## Update v0.2.1 -> v0.2.2

No database migration is required. Replace the application source while preserving `/opt/stocks-data-collector/.venv` and `/etc/stocks-data-collector.env`, then restart:

```bash
sudo systemctl restart stocks-data-collector
curl http://127.0.0.1:8790/health
```

The health response should report version `0.2.2`.

If v0.2.1 previously deactivated symbols after a failed bulk backfill, simply submit the same symbol list once after upgrading. v0.2.2 reactivates existing rows DB-first; symbols already holding >=100 candles are restored without SSI/Vnstock candle requests.

## Update v0.2.2 -> v0.2.3

No database migration is required.

1. Stop the service: `sudo systemctl stop stocks-data-collector`
2. Replace application source while preserving `.venv` and `/etc/stocks-data-collector.env`.
3. Restore ownership: `sudo chown -R stockscollector:stockscollector /opt/stocks-data-collector`
4. Start: `sudo systemctl start stocks-data-collector`
5. Verify: `curl http://127.0.0.1:8790/health` -> version `0.2.3`.

Recommended production verification: resubmit the same stock list once. Symbols whose `last_date` already equals the latest completed market date should log `ADD STOCK DB-FIRST ... provider calls skipped`. Stale symbols should run only Daily Sync for the missing newer edge. A prior failed bootstrap should retry Smart Backfill. Existing candles must remain visible even if a provider request fails.


## Update to v0.2.4

No database migration is required. Keep the existing `.venv` and `/etc/stocks-data-collector.env`, replace application source, then restart the systemd service. Verify `/health` reports `0.2.4`.

Production smoke test: re-submit a symbol whose PostgreSQL `MAX(trade_date)` already equals the latest completed D1 session. The journal should log `ADD STOCK DB-FIRST ... provider calls skipped` and must not show SSI/Vnstock calls for that symbol.
