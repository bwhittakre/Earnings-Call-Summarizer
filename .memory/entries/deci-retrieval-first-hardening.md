---
id: deci-retrieval-first-hardening
type: decision
project: earnings-call-summarizer
parent_id: deci-b76fadf8
title: Retrieval-first hardening pass — 5 instrumented hypotheses, ~4x faster plan run,
  plan/budget contradictions fixed
node_label: Retrieval-first hardening
tags: claims-desk,terminal-scoring,retrieval,performance,budget-gate,plan-mode,debug,september-2026
status: active
open_threads: 1
success: 'null'
files: ''
session_id: sess-bacdcd1a
created_at: '2026-09-02T17:05:00+00:00'
updated_at: '2026-09-02T17:05:00+00:00'
results:
  - metric: plan_run_wall_clock
    value: 5.8
    unit: s
    split: 41 open ops+HC trees, --plan, warm disk cache
    criterion: was 21.5s before the pass
    source: debug-bacdcd NDJSON instrumentation 2026-09-02
  - metric: retrieve_total
    value: 2.9
    unit: s
    split: 41 open trees, one --plan run
    criterion: was 16.3s after batching, 24.8s before
    source: debug-bacdcd NDJSON instrumentation 2026-09-02
  - metric: run_spend
    value: 0.39
    unit: USD
    split: 40 trees scored, $0 fallback budget, regenerated run
    source: data/terminal_score_candidates.json budget block 2026-09-02
---

Runtime-instrumented review of the retrieval-first code (debug mode; NDJSON logs over two
`--plan` runs the user executed) rather than a code-only read. Five hypotheses, each with a
log-backed verdict.

## Confirmed and fixed

- **Generic inference was 84% of retrieval time** (41.5s of 49.6s over two plan runs; the MSFT
  tree alone 10.6s for 8 anchors). Fixed in `scripts/_desk_retrieval.py` by (a)
  `infer_generic_many` — one pass over the ticker's sentences for all anchors; (b) a combined
  any-alias pre-filter regex per sentence so the per-anchor loop only runs on candidate
  sentences; (c) exclude-blanking only on sentences that already matched an alias; (d) a memo
  keyed by ticker + per-quarter content fingerprint (source_mtime, turn and sentence counts —
  a plain ticker+quarters key served a stale fixture in tests, so a rebuilt index would have too).
  Plan wall clock 21.5s → 5.8s warm; retrieval 16.3s → 2.9s; MSFT 10.6s → 0.14s. Output
  byte-identical (tiers, excerpt counts, evidence text).
- **`is_numeric_anchor` meant "contains a digit"**, so product codes were forced generic and
  through the co-occurrence gate they did not need: S600 (0.05 hits/q), ZUMA-2 (0.03), day 2
  (0.02), VX-445, KTE-X19, AMG 510, `2019 outlook` (0.0). Now "quantity-only": every
  normalised token is a number / currency / percent / scale word / connector. 8 trees flipped
  those anchors to specific; none regressed; GILD 7→9, REGN 17→20, TMO 15→16, AMGN 10→11
  excerpts. Remaining numeric_only set is exactly the real quantities (45%, 25%, $150 million…).
- **Ticker order thrashed the 2-ticker LRU** (ADI's ~40 index files loaded twice per run).
  The scorer's work list is now grouped by ticker (stable within a ticker).
- **`--plan` overwrote `data/terminal_score_candidates.json`.** The user's two plan runs
  clobbered the real Sonnet run (uncommitted; HEAD held the pre-retrieval-first output). Plan
  mode now writes `data/terminal_score_plan.json` (`PLAN_OUT`); the real run was regenerated:
  $0.39, 30 actionable, 4 needs_review, LRCX=missed, MSFT=delivered.
- **Budget contradictions in `scripts/_desk_terminal_candidates.py`:**
  - plan mode never charged the triage estimate, so a plan could never report
    `fallback_budget_exhausted` → `Budget.reserve()` books the estimate (marked `simulated`);
  - Tier-5 Sonnet after a triage was charged to the fallback line but never pre-flight gated →
    gated in `sonnet_judgment`; reason `fallback_budget_exhausted (triage ran, verdict not bought)`;
  - the deterministic `expired` rider only existed on the $0 path → shared `zero_evidence()`
    helper covers no-budget / triage-refused / budget-exhausted alike;
  - `_triage_corpus` appended a row before the char-cap check, offering Haiku one id it never saw.

## Rejected by evidence

- Incremental JSON writes after every tree: 84 writes, 456ms total, 5ms avg — left alone.
- Empty evidence excerpts from sid lookups: 0 of 471.

## Left alone (open thread)

`_BARE_SCALE_RE` canonicalises bare counts as currency ("1 million patients" → "$1 million
patient"). Applied identically to anchors and transcripts so matching still works, but it
conflates counts with dollars. Reverting needs an INDEX_VERSION bump and a ~1h index rebuild.

Tests: `tests/test_desk_retrieval_first.py` 58 passed / 1 xfail (new: quantity-only numeric
rule, product-code density, batched inference + memo invalidation, plan-mode exhaustion across
trees, Tier-5 Sonnet gate, expired rider on the exhausted path, triage-corpus id visibility).
All changes uncommitted per the no-auto-commit rule. Memory MCP timed out during this session
(duplicate angelo servers) — entry written directly.
