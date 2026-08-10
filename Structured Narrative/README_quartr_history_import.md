# Quartr historical transcript importer

Optional REST helper for unattended pulls when a Quartr API key exists.
**Live Roz onboard does not use this path.** History is seeded via the Cursor
Quartr MCP into `transcripts_raw/{TICKER}_FY….txt` (same `LocalFileProvider`
layout), then Onboard runs with `--skip-pull`. ROIC is only a disk-empty
fallback.

## Setup

```bash
export QUARTR_API_KEY=...                 # required; sent as x-api-key
# optional:
export QUARTR_API_BASE=https://api.quartr.com
```

## Output layouts (`LocalFileProvider`)

| Layout   | Path                                              |
|----------|---------------------------------------------------|
| `flat`   | `transcripts_raw/{TICKER}_FY2024-Q1.txt` (default) |
| `nested` | `transcripts_raw/{TICKER}/FY2024-Q1.txt`           |

## Usage

```bash
# 10-year lookback (flat layout)
python "Structured Narrative/quartr_history_import.py" --ticker AMZN --years 10

# Explicit window, nested layout, dry-run
python "Structured Narrative/quartr_history_import.py" \
  --ticker TXN --start 2016-01-01 --end 2026-08-01 --layout nested --dry-run --json
```

The Onboard orchestrator expects MCP-seeded `transcripts_raw` files (or
`--skip-pull` after an agent wrote them). It does not invoke this REST
importer. Keep the script for optional API-key environments only.

## API surface used

1. `GET /public/v3/companies?tickers=…` → `companyId`
2. `GET /public/v3/events?companyIds=…&startDate=…&endDate=…` (cursor pagination)
3. `GET /public/v3/documents/transcripts?eventIds=…`
4. `GET /public/v3/documents/transcripts/{id}` → transcript body
