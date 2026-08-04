# Quartr historical transcript importer

Scripted client for long-lookback (typically 10y) earnings-call history when
ROIC’s shorter window is not enough.

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

The Onboard orchestrator (`python -m services.earnings_monitor onboard`) calls
this importer for the 10y path and ROIC `fetch_transcripts` +
`export_inbox_to_transcripts_raw` for the 3y path.

## API surface used

1. `GET /public/v3/companies?tickers=…` → `companyId`
2. `GET /public/v3/events?companyIds=…&startDate=…&endDate=…` (cursor pagination)
3. `GET /public/v3/documents/transcripts?eventIds=…`
4. `GET /public/v3/documents/transcripts/{id}` → transcript body
