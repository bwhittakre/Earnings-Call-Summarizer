---
id: annotation-desk-roz-stale-dashboard
type: annotation
project: earnings-call-summarizer
parent_id: checkpoint-desk-ops-first-seeds
title: Claims Trees showed gold only because roz-dashboard-1 was 4 days stale
tags: annotation,desk,claims,roz,dashboard,august-2026
created_at: 2026-08-31T15:22:00+00:00
updated_at: 2026-08-31T15:22:00+00:00
---
`roz-dashboard-1` had been up since ~27 Aug. Compose later added
`./scripts` and `./services` binds, but the running container never
got them. `/app/scripts` stayed the image-baked five-file copy, so
`from scripts._desk_trees_v2` failed and Streamlit kept the gold-only
Book select.

Ops and healthcare JSON were already on `/history-source/output`
with locked stamps. Loaders were not the problem.

Fix: dashboard helpers now import `fiscal_key` / `clock_is_due` from
`claims_desk` (no private scripts import). Force-recreated
`roz-dashboard-1` on 31 Aug 2026. In-container loaders then return
`nvda_gold_v2`, `desk_ops_v2` (23), `desk_hc_v2` (20).
