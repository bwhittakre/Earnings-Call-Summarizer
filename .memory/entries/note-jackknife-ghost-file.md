---
id: note-jackknife-ghost-file
type: note
project: earnings-call-summarizer
parent_id: plan-rank-ic-phase1
title: Fast regen skips --jackknife, which left a stale artifact reading as current
node_label: Jackknife ghost-file trap
tags: gotcha,jackknife,regen,artifacts,rank-ic
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-17T20:01:00+00:00'
updated_at: '2026-08-17T20:01:00+00:00'
---
The single most expensive thing to rediscover in this codebase. Read this before trusting
any Rank IC artifact timestamp.

## The mechanism
`services/earnings_monitor/research_regen.py` builds the Rank IC command and appends
`--no-jackknife` whenever `fast_regen` is true. In `Structured Narrative/evaluate_narrative_signals.py`
each CSV was written only when the run produced rows for it, so an empty `jackknife_rows`
meant the write was simply skipped — and the **previous run's CSV stayed on disk**.

The dashboard reads each CSV independently but dates the whole bundle from `generated_at`
in `narrative_signal_eval.json`. So the surviving file rendered as current data from an
older book, with no warning anywhere in the UI. `render_jackknife` only warns when zero
rows match the filter, and stale rows match fine.

## How it surfaced
The 13 August rescoring run produced a bundle stamped 08-13 while
`narrative_signal_eval_jackknife.csv` was still from 08-10. Nothing flagged it. The
consolidated feature panel was independently stale from 08-11.

## The fix
Added `drop_stale_csv(path)` to `evaluate_narrative_signals.py`: if the current run did not
produce an artifact, any file left by an earlier run is deleted, so consumers hit the
missing-artifact path instead of reading stale data. Applied to all six conditional writes —
period_ic, jackknife, agreement, company_period, measure_members, primary_hypotheses — not
just jackknife, since every one had the same shape. Regression tests live in
`tests/test_evaluate_narrative_signals.py::DropStaleCsvTests`.

## Rule of thumb
An artifact that a run skipped must be removed, never left behind. Freshness is tracked per
bundle, not per file, so a surviving file inherits a timestamp it did not earn.
