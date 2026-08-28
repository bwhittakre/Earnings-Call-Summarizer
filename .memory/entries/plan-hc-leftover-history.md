---
id: plan-hc-leftover-history
type: plan
project: earnings-call-summarizer
parent_id: plan-healthcare-onboard
title: Overnight leftover-history score, then tagged healthcare stamp
node_label: Leftover history
tags: plan,healthcare,onboard,leftover,overnight,august-2026
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-08-26T17:35:00+00:00'
updated_at: '2026-08-26T17:35:00+00:00'
---
Prep only on 26 Aug 2026. Do not score until the user says go.

Two-quarter identity+join is done for LLY UNH DHR SYK GILD VRTX ELV.
Quant spines exist. Overlays stay two-quarter until `--apply-overlays`.

## Safe path (`scripts/_hc_leftover_history.py`)
1. Dry-run (default) — print proposed prior/output. Writes nothing.
2. `--apply-overlays` — expand overlays from on-disk transcripts. No LLM.
3. `--score` — `run_universe_batch` on the seven **without `--force`**.
   Refuses if overlays are still two-quarter.
4. `--stamp` — `evaluate_narrative_signals --output-tag healthcare_large_cap`
   on all 20 names. Refuses untagged write. Lock `generated_at` from that
   file. Do not invent a stamp.

## Hard rules
- Never `run_onboard`. Never `_healthcare_onboard_watch.py`.
- Never mix into live `xlk_tech` / SQLite Roz.
- Never `--force` (keeps FY2026-Q1/Q2).
- Never untagged `evaluate_narrative_signals` — locked tech book
  `generated_at=2026-08-17T17:28:40+00:00`.
- LLY ISIN `US5324571083` only. Lloyds `GB0005163141` stays dropped.
- ELV FY2015–2017 Q4 gaps stay missing.
- `production_v1` stays frozen. No holdout. No Rank IC until the tagged
  pack exists.
