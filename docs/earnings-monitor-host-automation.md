# Host automation (watchlist + calendar + concurrent live)

Operator-facing cheat sheet for the closed host loop. Python CLIs do the work;
Cursor Automation / Task Scheduler only dump Quartr MCP payloads and invoke CLIs.

## Layout

```text
config/automation_watchlist.yaml          # editable membership (tracked)
host_quartr/                              # gitignored runtime dumps
  calendar/{TICKER}.json                  # MCP list_events dumps
  transcripts/{event_id}.json             # MCP read_transcript dumps
  worklists/due_sweep.json                # due targets for live dispatch
earnings-scraper-main/.../inbox/events/   # watched *.event.json
earnings-scraper-main/.../inbox/          # *.transcript.json bundles
```

## Watchlist (add/remove anytime)

Empty watchlist = automate **nothing**. Overlay still required for publish.

```powershell
python -m services.earnings_monitor.host_automation watchlist list

# Whole company (all upcoming quarters)
python -m services.earnings_monitor.host_automation watchlist add --ticker OPAL

# One quarter only
python -m services.earnings_monitor.host_automation watchlist add --ticker STRW --period FY2026-Q2

# Remove one quarter
python -m services.earnings_monitor.host_automation watchlist remove --ticker STRW --period FY2026-Q2

# Remove company + prune watched manifests
python -m services.earnings_monitor.host_automation watchlist remove --ticker OPAL --prune-manifests
```

Remove takes effect on the next calendar/live cycle. In-flight SQLite monitor
rows are not auto-cancelled.

## Calendar cycle (every few hours)

1. For each ticker from `watchlist list`, Quartr MCP `list_events` →
   `host_quartr/calendar/{TICKER}.json`.
2. Publish + write due worklist:

```powershell
python -m services.earnings_monitor.host_automation calendar
```

Equivalent low-level:

```powershell
python -m services.earnings_monitor.calendar_publish `
  --from-json-dir host_quartr\calendar `
  --events-dir "earnings-scraper-main\earnings-scraper-main\inbox\events" `
  --worklist-out host_quartr\worklists\due_sweep.json `
  --due-within-hours 6
```

## Live cycle (near call / every few minutes when due)

1. Read `host_quartr/worklists/due_sweep.json`.
2. For each `event_id` still on the watchlist, MCP `read_transcript` →
   `host_quartr/transcripts/{event_id}.json`.
3. Concurrent dispatch:

```powershell
# Production default: loop LIVE→FINAL (do NOT pass --final unless escaping)
python -m services.earnings_monitor.host_automation live --max-workers 4 --loop
```

Each calendar/live run writes `host_quartr/health/last_run.json` for the Docker
monitor/dashboard (`host_feed_stale`, `host_missing_dump`, `host_dispatch_failed`).

Near `call_at`, missing dumps are **hard failures** (unless `--allow-missing-dump`).
Near-call dumps older than `--max-dump-age-minutes` (default 45) fail as `stale_dump`.

Escape hatch (skips LIVE print): `--once --final`.

## Cursor Automation prompt (copy/adapt)

**Calendar job**

1. Load `config/automation_watchlist.yaml` (or run `host_automation watchlist list`).
2. For each ticker, call Quartr `list_events` and write
   `host_quartr/calendar/{TICKER}.json`.
3. Run `python -m services.earnings_monitor.host_automation calendar` from the repo root.
4. Stop. Do not score.

**Live job**

1. If `host_quartr/worklists/due_sweep.json` is missing or `due_sweep` is empty, exit.
2. For each entry, call Quartr `read_transcript` for `event_id` and write
   `host_quartr/transcripts/{event_id}.json`.
3. Run `python -m services.earnings_monitor.host_automation live --max-workers 4 --loop`.
4. Stop.

## Task Scheduler one-liners

```powershell
cd "PATH\TO\Earnings Call Summarizer"
python -m services.earnings_monitor.host_automation calendar
python -m services.earnings_monitor.host_automation live --max-workers 4 --loop
```

Schedule calendar every 6 hours; schedule live every 5–15 minutes during earnings
windows (or only when the worklist is non-empty).

## Failure cards

| Symptom | Likely cause |
|---------|----------------|
| Calendar publishes nothing | Empty watchlist, or ticker has no overlay |
| Due worklist empty | No call_at within `--due-within-hours` |
| `skipped_reason=not_on_watchlist` | Quarter removed after worklist was written |
| `missing_dump` hard fail near call | MCP dump not written for that event_id |
| `stale_dump` | Dump mtime older than max-dump-age near call |
| `host_feed_stale` on Operations | Host calendar/live not running |
| Worker backlog | Many FINAL/LIVE jobs; single worker drains SQLite sequentially |

## Dry-run checklist

1. `watchlist add --ticker OPAL` (and optionally STRW + period).
2. Drop fixture dumps under `host_quartr/calendar/`.
3. `host_automation calendar` → manifests + worklist + `health/last_run.json`.
4. Drop `host_quartr/transcripts/{event_id}.json` fixtures.
5. `host_automation live --max-workers 2 --loop` → inbox bundles (LIVE then FINAL).
6. Confirm Operations shows host feed age; intentional missing dump near call → alert.
7. `watchlist remove --ticker OPAL --period FY2026-Q2 --prune-manifests` →
   that quarter stops auto-arming.

## Soak checklist (production hardening)

1. Arm one watchlist name with a future `call_at` → confirm **no** `stuck_event` email while awaiting.
2. Near call, omit the transcript dump once → `host_missing_dump` on Operations/Mailpit.
3. Restore dumps; confirm one LIVE score then FINAL rescore.
4. Force a LIVE workflow failure (bad model) → after retries, LIVE can score again on a new stagnated print.
5. Confirm research dirty clears via research-regen; thin peers / as-of pending surface as ranks alerts.
