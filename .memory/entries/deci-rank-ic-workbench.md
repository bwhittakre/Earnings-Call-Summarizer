---
id: deci-rank-ic-workbench
type: decision
project: earnings-call-summarizer
parent_id: plan-rank-ic-phase1
title: Rank IC workbench split into Research (read-only) and Lab (sandbox)
node_label: Research / Lab split
tags: dashboard,rank-ic,design,guardrail
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-17T20:02:00+00:00'
updated_at: '2026-08-17T20:02:00+00:00'
---
The load-bearing design decision behind the two new Roz pages.

## The split
- **Rank IC Research** (`services/earnings_monitor/dashboard/rank_ic_research.py`) is a
  read-only lens on the frozen production signal pack. Ten views, grouped into Explore
  (how a signal behaves across the book) and Explain (why one cell came out as it did).
- **Rank IC Lab** (`rank_ic_lab.py`) is the sandbox where weights change. Sliders over the
  same stored rows, scored head-to-head against a production baseline.

## Why
Nothing done in the Lab can alter production. The Lab reads stored `company_period` rows;
it never rescores transcripts, never writes `config/signal_packs/`, and never mutates the
production pack. Recipes and the experiment log live in a separate JSON store written
atomically via `lab_store.py`.

## The blend, and why it is not fitted
Each input is standardised point-in-time on an expanding window using prior periods only,
then combined as `sum(w*z) / sum(|w|)`. The weights are user-chosen, **not fitted to Rank
IC** — a fitted blend would quietly report its own training fit back as if it were a
result. History is used only to put Level and Quant z on a comparable scale.

Label, horizon and dimension are shared state across both pages, so loading a recipe
carries its context when switching.
