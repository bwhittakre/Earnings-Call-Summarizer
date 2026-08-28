---
id: note-hc-leftover-score-started
type: note
project: earnings-call-summarizer
parent_id: plan-hc-leftover-history
title: Leftover overlays applied; score fetching full history
node_label: Leftover score started
tags: note,healthcare,leftover,overnight,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-26T21:14:30+00:00'
updated_at: '2026-08-26T21:14:30+00:00'
---
26 Aug 2026. `--apply-overlays` wrote full-history overlays. LLY ISIN
stayed `US5324571083`. `--score` started without `--force` (skips
FY2025-Q4 / FY2026-Q1 / FY2026-Q2). Script PowerShell keep-awake
overflowed; a Python `SetThreadExecutionState` loop is running instead.

After LLM batch: rebuild leftover `feature_panel` with
`build_feature_panel.py --from-registry` before `--stamp`. Existing
two-quarter CSVs would otherwise let stamp run on stale 16-row panels.

13 already-onboarded names have full panels. Known one-quarter gaps
(not leftover work): CI FY2018-Q4, TMO FY2017-Q2. No Rank IC until
the tagged healthcare pack exists.
