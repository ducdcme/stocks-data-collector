# Stocks Data Collector v0.2.0-dev.3 — DEV 2 / Part 4

## Stock scanner universe

Added scanner groups:
- VN30
- HOSE
- HNX
- UPCOM

SSI is used to discover current group membership:
- `Securities` for HOSE/HNX/UPCOM
- `IndexComponents` for VN30

The scanner universe is deliberately separated from persisted data:
- `total`: symbols currently reported by SSI for the group
- `prepared`: active symbols already stored in PostgreSQL
- `missing`: group members not yet prepared/backfilled

No bulk historical backfill is triggered by reading or scanning a group.

## API

```text
GET /universe/groups
GET /universe/VN30
GET /universe/HOSE
GET /universe/HNX
GET /universe/UPCOM
```

Universe discovery is cached in memory for 5 minutes.

## Validation
- `pytest`: 40/40 PASS
