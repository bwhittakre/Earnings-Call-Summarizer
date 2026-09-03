---
id: chec-4a3ee31d
type: checkpoint
project: earnings-call-summarizer
parent_id: chec-7b3e2a91
title: Claims Desk review workbook built — 351 rows (41 verdicts + 310 seeds) across
  43 ticker tabs
node_label: Claims Desk review workbook built — 351 rows (41 v
tags: claims-desk,review,workbook,excel,seeds,verdicts,september-2026
status: active
open_threads: 0
success: 'null'
files: ''
session_id: sess-ee032a1f
created_at: '2026-09-03T12:50:18.867604+00:00'
updated_at: '2026-09-03T12:50:18.867604+00:00'
---
User briefing 2026-09-02: machinery + raw history are complete (1,578 transcripts indexed, all 145 clock-window quarters present, 72 CEO regimes), but the ops/HC books still hold only 44 trees because the 310 proposed seeds and 30 actionable verdicts were never reviewed. Regime analytics are meaningful for NVDA only until that human step happens. User chose to review ALL tickers at once.

Built `scripts/_desk_review_sheet.py`:
- `build` -> `data/desk_review_sheet.xlsx` (gitignored via *.xlsx). README + Summary tabs, then one tab per ticker (43). Section A = verdicts on existing trees (40 scored + CSCO needs_review row), Section B = proposed new seeds, sorted by seed quarter. Columns: Row ID (V:/S: prefix + tree_id), kind, title, seed qtr, clock, CEO at seed (from management_regimes.json via regime_for_fiscal), seed quote, proposal, outcome quote, confidence, verbatim flag (amber when NO), model reasoning, up to 3 other evidence excerpts, DECISION dropdown (Accept/Reject/Re-cite/Defer) with conditional colours, Notes. Summary tab uses live COUNTIF formulas per ticker.
- `read [--strict]` -> `data/desk_review_decisions.json` (committable): per-row decision + notes; strict mode fails on undecided rows. Reader locates columns by header text, ignores section rows.

Verified: 351 rows round-trip; Accept/Reject/Re-cite + notes read back correctly on real data rows.

Next: analyst fills the workbook; then an apply step types Accept rows into `_desk_trees_v2_catalogs.py` / `_hc_catalogs.py` (seeds with match blocks, verdicts as terminal nodes), rebuilds books + regimes sidecar, re-runs terminal scoring on the new trees (~$0.01/tree observed). Re-cite rows need the exact verbatim sentence first.
