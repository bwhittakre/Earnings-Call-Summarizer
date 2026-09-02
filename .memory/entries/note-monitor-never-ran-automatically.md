---
id: note-monitor-never-ran-automatically
type: note
project: earnings-call-summarizer
parent_id: plan-monitor-automation
title: The monitor has armed exactly one call automatically; every other run was by hand
node_label: Automation never actually ran
tags: gotcha,monitor,automation,forensics,arming
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-09-02T14:45:00+00:00'
updated_at: '2026-09-02T14:45:00+00:00'
---
Forensic read of the live monitor DB (`/data/monitor.sqlite3` in `roz-monitor-1`) on
2 September, prompted by asking whether ADSK armed for its 27 August call.

## The evidence
Eight events exist in the DB, total, covering five weeks and eight companies:

| ticker | period | state | manual_override | provider_event_id |
|---|---|---|---|---|
| NVDA | FY2027-Q2 | complete | 1 | 676136 |
| OPAL | FY2026-Q2 | failed | **0** | 665958 |
| STRW | FY2026-Q2 | complete | 1 | 692045 |
| SPCX | FY2026-Q2 | complete | 1 | quartr:692542 |
| CTSH | FY2026-Q2 | complete | 1 | manual:CTSH:FY2026-Q2 |
| TXN | FY2026-Q2 | complete | 1 | manual:TXN:FY2026-Q2 |
| AMZN | FY2026-Q2 | failed | 1 | manual:AMZN:FY2026-Q2 |
| AAPL | FY2026-Q3 | complete | 1 | quartr:658553 |

**Seven of eight carry `manual_override=1`.** OPAL is the only event that ever arrived
through automatic discovery -- and OPAL is one of the five names that passed the old
book-intersect-overlays gate, so that is exactly consistent.

## What this means
The automated cycle has never run. What looked like "the scanner works for tech but not
healthcare" was really "someone hand-armed each tech call, and nobody hand-armed ADSK."
Three of the IDs are literally `manual:<TICKER>:<PERIOD>`.

Note that `arm` refuses a ticker with no overlay ("onboard first"), but the branch above
that check calls `ensure_ticker_in_book` instead and skips it -- which is how AAPL, TXN and
CTSH were armed despite having no overlay file.

## ADSK specifically
Zero rows in the events table. Last scored quarter is FY2027-Q1; the 27 August FY2027-Q2
call was never processed. Its output artifacts stop at 13 August.

ADSK was blocked by **two independent gates**, and the eligibility fix only clears one:
1. **No event source.** `EARNINGS_MONITOR_PROVIDER=watched` reads manifests from
   `inbox/events/`, which holds exactly one file (`NVDA-FY2027-Q2.event.json`).
   `host_quartr/` does not exist and the watchlist is empty, so nothing generates manifests.
   Without a manifest, discovery never sees ADSK at all.
2. **Eligibility.** ADSK is in `roz_book_tickers` but has no overlay, so the old
   intersection dropped it. This is the half now fixed.

## Open thread
Phase 1 alone would **not** have caught ADSK. Phase 2 (a real event source) is the binding
constraint, not eligibility.
