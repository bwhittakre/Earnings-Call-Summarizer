---
id: chec-4d2e9a71
type: checkpoint
project: earnings-call-summarizer
parent_id: deci-b76fadf8
title: Retrieval-first terminal scoring — implemented and run (43/44 trees resolve
  at free tiers; 30 actionable verdicts for $0.41)
node_label: Retrieval-first scoring shipped
tags: claims-desk,terminal-scoring,retrieval,transcripts-index,budget-gate,needs-review,september-2026
status: active
open_threads: 3
success: 'null'
files: ''
session_id: sess-1f0c19b0
created_at: '2026-09-02T15:50:00+00:00'
updated_at: '2026-09-02T15:50:00+00:00'
results:
  - metric: trees_resolved_free_tiers
    value: 43
    unit: of 44
    split: alias audit, ops+HC open trees, after match blocks
    source: data/retrieval_alias_audit.txt 2026-09-02
  - metric: actionable_verdicts
    value: 30
    unit: trees
    split: 41 open ops+HC trees, $0 fallback budget
    criterion: edge != none and confidence >= medium
    source: data/terminal_score_candidates.json 2026-09-02
  - metric: run_spend
    value: 0.41
    unit: USD
    split: 40 Sonnet calls incl. 3 re-scores
    source: data/terminal_score_candidates.json budget block
---
Written directly to `.memory/entries/` because the memory MCP timed out three
times on 2026-09-02 ~11:45 ET; server should sync it on next start.

All eight plan steps implemented 2026-09-02 (uncommitted, in working tree — the
user controls commits).

**Built**
- `scripts/_desk_transcript_backfill.py` — resumable Quartr back-fill;
  `data/transcript_backfill_manifest.json`. All 145 clock-window quarters for
  the 41 open ops/HC trees are present.
- `scripts/_desk_transcript_index.py` — sentence-level index per transcript
  (speaker role via roster/handoff heuristics, boilerplate strip, deterministic
  `normalize_text`). INDEX_VERSION=4 (v4 = normaliser fixes: `percentage
  points` no longer folded to `%`; `-sses` plurals converge). 1,578 transcripts
  indexed incl. ~770 found in per-ticker subdirs; 132 are genuinely unlabeled
  dumps and index as `Unknown Speaker`.
- `scripts/_desk_retrieval.py` — MatchBlock (anchors/context/exclude/generic),
  alias derivation, generic inference (>2 hits/quarter), Tier 0–3 ladder (T0
  exact + catalog context, T1 alias, T2 + seed nouns ±3 sentences same turn,
  T3 widened to all post-seed quarters), ranking, `--alias-audit` / `--show`.
  Analyst/operator sentences are never returned.
- Catalogs: `match` blocks on all 41 open trees
  (`scripts/_desk_trees_v2_catalogs.py`, `_hc_catalogs.py`); clock dates
  removed from `objects` (ABBV 2022, VRTX mid-2019, LRCX mid-2016).
  `normalize_match` in `scripts/_desk_trees_v2.py`.
- `scripts/_desk_terminal_candidates.py` rewritten: retrieval-first evidence,
  `--plan` (zero API calls, cost estimate), `--fallback-budget-usd` (default
  $0; gates Tier 4 Haiku triage → Tier 5 Sonnet), `needs_review` with 9
  reasons, per-candidate retrieval ledger (tier / paragraphs / tokens / usd /
  alias snapshot), expired guard (only when clock passed AND window complete
  AND zero hits; LLM `expired` downgraded otherwise), verbatim excerpt
  verification, filtered `--tree` re-scores merge into the existing output.
- `scripts/_desk_seed_batch.py` proposes a match block per seed
  (`propose_match_block`, drops date-only anchors).
- Workshop HTML: Needs Review banner (reason + unblock hint), run-budget
  header, Tier / Paragraphs / Cost columns.
- `tests/test_desk_retrieval_first.py`: 51 pass, 1 xfail (no word-number
  folding — by design).

**Results (2026-09-02 run, 41 open trees, $0 fallback)**
- Alias audit after match blocks: 43/44 resolve at free tiers (T0 32, T3 11);
  only CSCO unresolved (zero transcripts). Before match blocks: 35/44.
- Scoring: 40 scored (31 T0, 9 T3), 30 actionable, 3 needs_review (csco
  no_transcripts_indexed; abbv llm_low_confidence — excerpt not verbatim; aapl
  expired_guard — no-clock goal). Spend $0.41 / 40 Sonnet calls.
- msft-build-analyst-briefing (the user's worked example) → delivered
  FY2017-Q3 on the verbatim "We will also host our financial analyst briefing
  on May 10th."
- lrcx-klx first scored `expired`; prompt tightened (missed > expired whenever
  evidence speaks to the outcome) → re-scored `missed`.

**Open / next**
- Human review of the 30 actionable verdicts in the Workshop before typing
  terminal nodes.
- CSCO has no transcripts for its FY2019+ window — needs a source.
- Index v4 rebuild was running at checkpoint time; scoring results were
  produced on v3 (differences limited to `percentage points` / `-sses` tokens).
- Memory MCP unreachable this session — check `angelo doctor`.
