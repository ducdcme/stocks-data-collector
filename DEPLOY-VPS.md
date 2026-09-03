# Deploy VN Stocks Data Collector v0.2.6 on Ubuntu VPS

GitHub is the source of truth for application code. Production runtime state, PostgreSQL data, logs and secrets remain on the VPS and are never committed to Git.

Recommended layout:

```text
/opt/stocks-data-collector
/opt/stocks-data-collector/.venv
/etc/stocks-data-collector.env
PostgreSQL DB: stocks_data
HTTP: 127.0.0.1:8790
```

## 1. First install from GitHub

Create the application directory and clone the private repository:

```bash
sudo mkdir -p /opt/stocks-data-collector
sudo chown -R $USER:$USER /opt/stocks-data-collector
git clone <YOUR_GITHUB_REPO_URL> /opt/stocks-data-collector
cd /opt/stocks-data-collector
git fetch --tags
git checkout v0.2.6
```

Create the virtual environment and install dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 2. PostgreSQL

Create a dedicated DB/user if this is a new installation:

```sql
CREATE USER stockscollector WITH PASSWORD 'CHANGE_ME';
CREATE DATABASE stocks_data OWNER stockscollector;
```

Existing installations keep the current database. Do not recreate it during upgrades.

## 3. Environment file

Create `/etc/stocks-data-collector.env` and keep real secrets only on the VPS:

```env
STOCKS_HOST=127.0.0.1
STOCKS_PORT=8790
STOCKS_DATABASE_URL=postgresql://stockscollector:CHANGE_ME@127.0.0.1:5432/stocks_data
STOCKS_PROVIDER_PRIMARY=ssi
STOCKS_PROVIDER_FALLBACK=vnstock
SSI_CONSUMER_ID=...
SSI_CONSUMER_SECRET=...

STOCKS_CORPORATE_ACTION_AUTO=true
STOCKS_CORPORATE_ACTION_LOOKBACK_DAYS=45
STOCKS_CORPORATE_ACTION_FACTOR_TOLERANCE=0.0005
STOCKS_CORPORATE_ACTION_PRICE_TOLERANCE=0.05
```

Protect it:

```bash
sudo chmod 600 /etc/stocks-data-collector.env
```

## 4. Database migrations

Load the production environment and apply all migrations:

```bash
cd /opt/stocks-data-collector
. .venv/bin/activate
set -a
source /etc/stocks-data-collector.env
set +a
python -m scripts.migrate
```

v0.2.5 adds:

```text
migrations/002_corporate_action_events.sql
```

This migration records already-processed SSI corporate-action events so historical reconciliation is not repeated every day.

## 5. systemd

Create `/etc/systemd/system/stocks-data-collector.service` if not already installed:

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

Enable/start and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now stocks-data-collector
sudo systemctl status stocks-data-collector
curl http://127.0.0.1:8790/health
curl http://127.0.0.1:8790/health/db
```

`/health` must report version `0.2.6`.

## 6. Upgrade an existing v0.2.5 installation to v0.2.6

Back up the PostgreSQL database according to the VPS backup policy before a release upgrade. Then deploy the tested Git tag:

```bash
cd /opt/stocks-data-collector
git status
git fetch --tags
git checkout v0.2.6

. .venv/bin/activate
pip install -r requirements.txt

set -a
source /etc/stocks-data-collector.env
set +a
python -m scripts.migrate

sudo systemctl restart stocks-data-collector
curl http://127.0.0.1:8790/health
curl http://127.0.0.1:8790/health/db
journalctl -u stocks-data-collector -n 100 --no-pager
```

Do not overwrite `/etc/stocks-data-collector.env`, PostgreSQL data, `.venv`, logs or runtime backups from Git.

## 7. Production smoke checks

Check persisted coverage:

```bash
cd /opt/stocks-data-collector
. .venv/bin/activate
set -a
source /etc/stocks-data-collector.env
set +a
python -m scripts.stats --symbols MBB VIX NTP
```

Inspect processed corporate actions if needed:

```bash
python -m scripts.corporate_action_events --symbols MBB VIX NTP
```

Normal daily sync automatically performs SSI corporate-action lookback even when the newer DB edge is already current:

```bash
python -m scripts.sync_daily --symbols MBB VIX NTP
```

Manual diagnostic/recovery remains available. Write mode is allowed only when SSI independently verifies every requested event:

```bash
python -m scripts.corporate_action --symbol MBB --event-date 2026-08-11
python -m scripts.corporate_action --symbol MBB --event-date 2026-08-11 --apply --force
```

## 8. Rollback code

If v0.2.6 has an application-level problem, stop the service and checkout the previous tested tag:

```bash
cd /opt/stocks-data-collector
sudo systemctl stop stocks-data-collector
git fetch --tags
git checkout v0.2.4
. .venv/bin/activate
pip install -r requirements.txt
sudo systemctl start stocks-data-collector
curl http://127.0.0.1:8790/health
```

Migration `002_corporate_action_events.sql` only adds event-state storage; leaving the table in place is safe for an application-code rollback. Do not drop production data during rollback.
