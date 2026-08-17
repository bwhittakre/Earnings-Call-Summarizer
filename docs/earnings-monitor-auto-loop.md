# Automatic live-print loop (onboarded companies)

For tickers already onboarded (company overlay + history + Roz book), Roz can
**detect the next earnings call and run the live→final path** without a
per-quarter manual `arm`. Operator work shrinks to: keep Docker up, maintain the
**automation watchlist**, and keep a host MCP/automation job refreshing Quartr
(calendar + transcript dumps).

Full operator cheat sheet:
[`earnings-monitor-host-automation.md`](earnings-monitor-host-automation.md).

## Architecture

```text
onboard (once) → overlay + book
watchlist add/remove (anytime) → config/automation_watchlist.yaml
host calendar dumps → host_automation calendar / calendar_publish
  → inbox/events/*.event.json + host_quartr/worklists/due_sweep.json
monitor (PROVIDER=watched) → discover → lifecycle
near call: MCP transcript dumps → host_automation live (concurrent)
  → inbox/*.transcript.json
worker → one LIVE post_call, then FINAL re-score → research-regen
  → FINAL also refreshes book ranks (see book-ranks.md)
```

## Prerequisites

1. **Onboard once** per ticker (MCP history + ISIN as needed) so
   `Structured Narrative/config/company_overlays/{TICKER}.json` exists and the
   ticker is on the Roz book / sector file.
2. **Add to automation watchlist** (empty = automate nothing):

```powershell
python -m services.earnings_monitor.host_automation watchlist add --ticker OPAL
# or one quarter:
python -m services.earnings_monitor.host_automation watchlist add --ticker STRW --period FY2026-Q2
```

3. **Compose mounts** (already in `docker-compose.yml`):
   - `./config` → `/app/config` (fiscal + sectors + watchlist)
   - `./Structured Narrative/config` → `/app/Structured Narrative/config` (overlays)
4. **`EARNINGS_MONITOR_PROVIDER=watched`** (default in `.env.sim.local` /
   `.env.example` for local assisted mode).
5. Event manifests directory:
   `earnings-scraper-main/earnings-scraper-main/inbox/events` (Compose default).

## Host dump layout

```text
host_quartr/calendar/*.json
host_quartr/transcripts/{event_id}.json
host_quartr/worklists/due_sweep.json
```

(`host_quartr/` is gitignored.)

## Host jobs

### 1. Calendar publish (auto-arm)

```powershell
# After writing MCP list_events dumps into host_quartr/calendar/
python -m services.earnings_monitor.host_automation calendar
```

Low-level equivalent:

```powershell
python -m services.earnings_monitor.calendar_publish `
  --from-json-dir host_quartr\calendar `
  --events-dir "earnings-scraper-main\earnings-scraper-main\inbox\events" `
  --worklist-out host_quartr\worklists\due_sweep.json `
  --horizon-days 30 `
  --due-within-hours 6
```

- Only **watchlist ∩ overlays** are published (period rules apply).
- Idempotent: same `provider_event_id` overwrites metadata only; manual `arm`
  (`manual_override`) still wins.

### 2. Concurrent live transcript feed

```powershell
# After writing MCP read_transcript dumps into host_quartr/transcripts/{event_id}.json
python -m services.earnings_monitor.host_automation live --max-workers 4 --final
```

Single-event helper still available:

```powershell
python -m services.earnings_monitor.live_print_loop `
  --event-id 665958 `
  --ticker OPAL `
  --period FY2026-Q2 `
  --dump host_quartr\transcripts\665958.json `
  --inbox "earnings-scraper-main\earnings-scraper-main\inbox" `
  --once --final
```

## Monitor eligibility vs automation watchlist

| Gate | Rule |
|------|------|
| Monitor discover / standard arm | Roz book ∩ overlays |
| Host calendar / live dispatch | Automation watchlist ∩ overlays (period-aware) |

Production names should still be listed in `EARNINGS_MONITOR_TICKERS`; the
watchlist is the intentional “what to auto-arm/sweep” set.

## Scoring policy (unchanged)

- At most **one LIVE** `post_call` while the transcript is live.
- **FINAL** may re-score when the final fingerprint arrives.
- See `earnings-monitor-setup.md` for stagnation / live-growth knobs.

## Failure cards

| Symptom | Likely cause |
|---------|----------------|
| Calendar publishes nothing | Empty watchlist, or no overlay |
| Manifest published but never discovered | Ticker missing from book/env; check discover eligibility |
| Discover empty every cycle | `PROVIDER=manual`, or empty `inbox/events` |
| `not_on_watchlist` / pruned | Quarter or company removed from watchlist |
| `host_missing_dump` / `stale_dump` | Host MCP dump missing or too old near call |
| `host_feed_stale` | Host automation not writing `host_quartr/health/last_run.json` |
| False `stuck_event` on pre-call wait | Should not fire before `call_at`+grace (state-aware) |
| LIVE never retries after fail | Exhausted LIVE failure should clear gate → TRANSCRIPT_PENDING |
| `research_book_stale` | Dirty age exceeds debounce+idle, or last regen failed |
| `book_ranks_thin_peers` / `asof_overdue` | Peer set below min_names, or investable-asof pending past grace |
| Worker backlog | Concurrent host sweeps OK; single worker scores sequentially |
| Quant / IDs fail | Snowflake network policy / missing ISIN in overlay |

## Dry-run proof

```powershell
python -m services.earnings_monitor.host_automation watchlist add --ticker OPAL
python -m services.earnings_monitor.calendar_publish `
  --from-json-dir path\to\calendar_dumps `
  --events-dir "earnings-scraper-main\earnings-scraper-main\inbox\events" `
  --worklist-out host_quartr\worklists\due_sweep.json

python -m services.earnings_monitor.host_automation live --max-workers 2 --loop
```

## Out of scope

- Quartr REST inside Docker
- Auto-onboard of brand-new tickers (still explicit `onboard`)
- Auto-enrolling the entire Roz book into the watchlist
- Auto-cancel of in-flight SQLite events on watchlist remove
- Multi-worker Docker scoring
