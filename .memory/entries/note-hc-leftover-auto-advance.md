---
id: note-hc-leftover-auto-advance
type: note
project: earnings-call-summarizer
parent_id: plan-healthcare-onboard
title: Auto-advance leftover two-quarter LLM as each job finishes
node_label: Auto-advance leftovers
tags: healthcare,onboard,leftover,preference,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-26T16:35:00+00:00'
updated_at: '2026-08-26T16:35:00+00:00'
---
26 Aug 2026. User left the desk and granted full permission to
auto-advance leftover two-quarter scoring when each prior job finishes.

Queue after GILD (in flight): VRTX, then ELV. One LLM at a time. Same
command: `run_company_pipeline.py --quarters FY2025-Q4 FY2026-Q1
FY2026-Q2 --extra-output-quarters FY2026-Q1 FY2026-Q2 --batch
--skip-quant --skip-bridge`.

On each finish: confirm 16-row panel, chronological Q4→Q1 and Q1→Q2
deltas, join 0 issues, write a checkpoint. Do not call full
`run_onboard`. Do not stamp `healthcare_large_cap`. Do not compute
Rank ICs. Do not mix into live `xlk_tech` / SQLite Roz.

Stop after ELV's two-quarter panel passes. Full-history scoring of
the seven leftovers is a later, separate go.
