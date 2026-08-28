---
id: chec-desk-claims-roz-onboard
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-desk-claims-roz
title: Claims Desk fully onboarded onto live Roz
node_label: Claims Desk onboarded
tags: checkpoint,desk,claims,roz,docker,august-2026
status: active
open_threads: 0
success: 'true'
files: ''
created_at: '2026-08-27T14:42:00+00:00'
updated_at: '2026-08-27T14:42:00+00:00'
---
27 Aug 2026. Claims Desk is a first-class Roz page that survives
container recreate. Stamp `2026-08-17T17:28:40+00:00`.

Compose bind-mounts `services/earnings_monitor/dashboard` into
`roz-dashboard-1` (read-only). Nested reports mount needs
`dashboard/static/reports` on the host. Host Python edits now
reach `:8501` without an image rebuild. Shared monitor image
was not rebuilt (worker / research-regen left on the 7-day
image). Healthcare stayed out. No remaining-125 dump.

`docker compose up -d dashboard` re-ran history-import as a
dependency. Live parquet is the 21-name `EARNINGS_MONITOR_TICKERS`
set (6,700 records / 855 quarters). Earlier Roz session showed
24 / 907. Extra sector names (CSCO, AMD, STRW, OPAL, CBRS) were
not in that ticker env. Claims-book names are all still in the
21. production_v1 untouched.
