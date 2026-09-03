---
id: chec-7b3e2a91
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-desk-claims
title: Claims Desk Growth Pipeline built, run, and hardened
node_label: Growth pipeline — seed batch + terminal scoring
tags: desk,claims,llm,seed-batch,terminal-scoring,workshop,september-2026
status: active
open_threads: 4
success: 'null'
files: scripts/_desk_seed_batch.py, scripts/_desk_terminal_candidates.py, scripts/_desk_trees_workshop_html.py,
  services/earnings_monitor/dashboard/claims_trees.py, data/seed_batch_candidates.json,
  data/terminal_score_candidates.json
session_id: sess-e602b524
created_at: '2026-09-01T19:08:00+00:00'
updated_at: '2026-09-03T17:13:53.399848+00:00'
---
Follows the Management Regimes checkpoint (chec-9fb8d5c8). Regimes analytics were
architecturally complete but starved: ops/HC books held 44 skeleton trees with
~0.1 scored nodes each, while 1,143 seedable cue rows sat uncovered. Novelty data
was already fully ingested (30–44 quarters per ticker) — the gap was seeding and
scoring, not "the pull". Built per terminal_scoring_pipeline_a53e9ca7.plan.md.

## What was built
1. **scripts/_desk_seed_batch.py** — one LLM call per ticker over all missed cue
   rows; proposes 3–8 seeds with full tree dict (`proposed_seed_py`). Priority
   order: regime-transition tickers first (IBM, ABBV, JNJ, MDT, UNH, DHR, SYK).
   NVDA gold excluded ("no new LLM on the gold run"). BUCKETS constant drives the
   prompt (not a hardcoded copy).
2. **scripts/_desk_terminal_candidates.py** — one LLM call per open ops/HC tree;
   gathers post-seed novelty excerpts mentioning the tree's objects (cap 20) and
   proposes delivered/hit/missed/expired/none with `proposed_node_py`.
3. **Workshop HTML** — `renderSeedCandidates` / `renderTerminalCandidates`
   sections, gated on file existence; `claims_trees.workshop_bundle` gains
   `seed_candidates` + `terminal_candidates` loaders (None if absent/corrupt).

Convention preserved: propose, never auto-insert. Both output files carry a
"Do not auto-insert" header.

## First run (2026-09-01)
- Seed batch: 43 tickers, 1,143 cue rows → **310 proposed seeds** (~20 min).
- Terminal scoring: **41 open trees → 21 actionable** (7 delivered, 3 hit,
  2 missed, 9 expired, 20 none).
- Cost: model claude-sonnet-4-5; usage counters were 0 on this run (bug fixed
  below), so the real spend is unrecorded — plan estimate was ~$6–12.

## Hardening from two debug passes
- LLM occasionally returns a JSON array instead of an object → list→dict guard
  (crashed on MU/mu-s600-seagate mid-run before the fix).
- Both scripts now flush output after every ticker/tree (`_write_output`,
  `complete` flag; Workshop shows PARTIAL RUN banner) — the MU crash had lost
  13 verdicts.
- Token usage now accumulated via `client._accumulate_usage` (direct
  `messages.create` bypassed the AnthropicClient counters).
- **Excerpt provenance**: `excerpt_verified` per candidate + `n_excerpt_unverified`
  header; Workshop "Cite" column (✓ / ✗ paraphrased). 12/310 seeds and 1 scored
  verdict (MRK/mrk-dividend-15 → delivered) quote text not verbatim in source —
  `build_ops_book(verify_excerpts=True)` would reject them; analyst re-cites first.
- Security audit clean: no secret in outputs/HTML, all LLM fields `esc()`'d,
  `</` → `<\/` blob guard, write surface limited to `data/`.

## Open threads
- Analyst review of 310 seeds / 21 verdicts in the Workshop, then type accepted
  entries into `_desk_trees_v2_catalogs.py` / `_desk_trees_v2_hc_catalogs.py` and
  rebuild books — regime analytics fire only after that.
- Re-run terminal scoring after new seeds land (~400 trees, ~$15–20 est.).
