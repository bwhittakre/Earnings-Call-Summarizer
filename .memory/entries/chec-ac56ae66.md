---
id: chec-ac56ae66
type: checkpoint
project: earnings-call-summarizer
parent_id: deci-b76fadf8
title: 'Step 0 back-fill: P1 clock windows complete (141/145), resumable tool built'
node_label: 'Step 0 back-fill: P1 clock windows complete (141/1'
tags: retrieval-first,backfill,transcripts,quartr
status: active
open_threads: 0
success: 'null'
files: ''
session_id: sess-1f0c19b0
created_at: '2026-09-01T20:53:55.462871+00:00'
updated_at: '2026-09-01T20:53:55.462871+00:00'
results: '[{"metric": "p1_clock_window_coverage", "value": 141, "unit": "transcripts
  present", "split": "P1 = clock windows of 41 open ops/HC trees", "criterion": "145
  cells; 4 no_event", "source": "data/transcript_backfill_manifest.json"}, {"metric":
  "p2_missing", "value": 596, "unit": "transcripts", "split": "P2 = post-seed quarters
  of open trees", "source": "data/transcript_backfill_manifest.json"}]'
---
Built scripts/_desk_transcript_backfill.py (plan / events / stage / no-event / status). Manifest data/transcript_backfill_manifest.json: 1,562 desk-covered (ticker, period) cells across 42 ops+HC tickers, prioritised P1 = clock window (seed+1..clock+2, max 6) of an open tree, P2 = post-seed quarter of an open tree, P3 = other. Event ids in data/transcript_backfill_events.json.

Result this session: P1 141 present, 4 no_event (CTSH FY2017-Q1..Q4 — Quartr has no earnings-call event before May 2018, only proxy filings). P2 596 missing / 524 present, P3 143 missing — all 18 tech tickers; HC tickers were already fully covered by earlier MCP waves. P2/P3 pull is resumable: run `stage --priority-max 2` for the work queue (TODO/NEXT/NEED_EVENTS lines).

Verified the worked example: MSFT FY2017-Q4 raw now contains Amy Hood's "The key trends for FY 2018 from the financial analyst briefing remain largely unchanged." — the confirmation the novelty-only scorer could not see.

Raw transcript formats: Quartr pulls = `Speaker:` line then paragraph lines; recent pipeline files = `Speaker: text` single-line turns. Indexer must parse both.
