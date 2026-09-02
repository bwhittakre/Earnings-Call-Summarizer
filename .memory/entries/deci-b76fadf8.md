---
id: deci-b76fadf8
type: decision
project: earnings-call-summarizer
parent_id: chec-7b3e2a91
title: Retrieval-first terminal scoring — design decisions locked, plan written, not
  implemented
node_label: Retrieval-first terminal scoring — design decision
tags: claims-desk,terminal-scoring,retrieval,alias-matching,plan
status: active
open_threads: 3
success: 'null'
files: ''
session_id: sess-1f0c19b0
created_at: '2026-09-01T20:30:54.897207+00:00'
updated_at: '2026-09-01T21:18:17.389968+00:00'
---
Diagnosis (2026-09-01 run, 41 open ops/HC trees): the terminal scorer judges trees against novelty_view evidence, which averages 0.90 excerpts/quarter. 27 of 41 trees had ZERO object-matched excerpts; _gather_evidence's fallback then handed the LLM 20 unrelated excerpts and 7 came back 'expired' (5 high-confidence). Worked example msft-build-analyst-briefing: 38 post-seed quarters, 29 novelty excerpts, 0 matches, expired[high]; the only retained mention ('deferred ... to the analyst day', FY2017-Q3 dimensions) is phrased differently from both objects and lives in a file the scorer never reads. Raw transcripts are retained only from FY2024-Q4.

Decision: replace novelty evidence with retrieval over raw transcripts, retrieval-first (local, deterministic, free), with a budget-gated paid fallback.

Brainstorm decisions locked with the user:
- Generic co-occurrence window: ±3 sentences (not whole speaker turn).
- Analyst turns EXCLUDED at retrieval; ALL management turns kept regardless of which executive; an executive's answer to an analyst counts, the question does not.
- Numeric targets: STRICT matching only; unresolved go to a prominent needs_review queue, never to fallback or a verdict.
- generic flag: INFERRED from hit density (>2.0 hits/quarter to start), optional explicit catalog override.
- All seven anti-creep levers in v1: pre-flight token estimate; run budget default $0.00 (--fallback-budget-usd opt-in); --plan mode (zero API calls); Haiku triage returning sentence ids before Sonnet; fallback bounded to clock window (max 6 quarters), no clock => no fallback; cache-aware per-ticker grouping; per-candidate retrieval ledger + run budget block in output.
- Match block replaces flat objects: anchors / context / exclude / generic. Date-like objects (mid-2016, mid-2019, 2022) move out of objects into clocks.
- Expired guard: 'expired' only when every clock-window transcript marked present in the backfill manifest was searched and returned zero; missing transcript => needs_review(transcript_missing).
- Zero-hit trees do not call the LLM at all (default run is cheaper than today).
- Prerequisite Step 0: back-fill transcripts_raw FY2016–FY2024 for 41 ops/HC tickers via Quartr staging + existing scripts/_assemble_quartr_windows.py; NVDA gold excluded (No transcripts_raw / No new LLM rule stands).

Plan file: ~/.cursor/plans/retrieval_first_scoring_c4e81f2a.plan.md (8 todos, all pending). User explicitly said do NOT auto-implement.
