---
id: note-reissued-event-id
type: note
project: earnings-call-summarizer
parent_id: plan-monitor-automation
title: A moved earnings call arrives under a new Quartr event ID and used to be dropped
node_label: Rescheduled-call drop
tags: gotcha,monitor,discovery,quartr,scheduling
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-09-02T14:10:00+00:00'
updated_at: '2026-09-02T14:20:00+00:00'
---
The second silent failure in `service.discover`, independent of the eligibility bug.

## The mechanism
Quartr mints a **fresh event ID** when a call moves. The replacement therefore arrives
looking like an unrelated event for a quarter already tracked. `discover` matched it on
(ticker, fiscal_period), logged `Ignoring provider event ID change`, and dropped it -- so
the monitor stayed armed for the old, wrong date.

The adjacent branch already did the right thing when the *same* ID came back with changed
times ("provider schedule corrections update only event metadata"), which shows the intent
was always to absorb schedule changes. The ID-change path was simply never handled. No test
covered it either way.

## Why it cannot just insert the new event
`events` is `UNIQUE(ticker, fiscal_period)` with `provider_event_id` as the primary key, and
three tables (`jobs`, `job_runs`, `artifact_publications`) carry that ID as a foreign key
under `PRAGMA foreign_keys=ON`. Rebinding the ID would mean cascading four tables. So
`_absorb_reschedule` keeps the **original** `provider_event_id` and takes only the new
times, via `dataclasses.replace(event, provider_event_id=old_id)`. Lifecycle, queued jobs
and run history all stay attached.

## Guards
Only absorbed in `RESCHEDULABLE_STATES` (pre-call) and never when `manual_override` is set,
so an operator's schedule still wins. Regression tests are in
`tests/test_earnings_monitor_assisted.py`.

## Open thread
`FAILED` is deliberately excluded, so a failed event that Quartr later reissues will not be
picked up automatically. OPAL has been sitting in FAILED since 13 August with a transcript
timeout and still needs a manual decision.
