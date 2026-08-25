---
id: plan-tech-lab-case-study
type: plan
project: earnings-call-summarizer
parent_id: plan-rank-ic-phase1
title: 'Tech Lab case study: a-priori industry hypotheses vs natural Rank IC'
node_label: Tech Lab case study
tags: plan,rank-ic,lab,tech,case-study,august-2026
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-08-18T15:30:00+00:00'
updated_at: '2026-08-18T15:30:00+00:00'
---
Case study of **industry stories**, not kitchen-sink blends.

## Locked before numbers
- Split: 17 Aug book, `asof` / `0_56`, same-window overlap with each recipe's
  natural baseline.
- Weights: sparse integers, chosen from tech economics. Not fitted. Not the
  18 Aug `equal_call_date` / `narrative_only` recipes.
- Lab constraint: one dimension per recipe.
- Sleeves: `semis_cycle` (10 names), `software_cloud` (7), `all` (25).
- Natural bar: single-signal Rank IC of the named `baseline_signal` on the
  same dimension / universe / periods.
- Rollup pass: at least 3 of 7 **story** recipes beat their natural baseline.
  `H8` is a control and does not count toward the 3.

## Spec
`config/signal_packs/tech_lab_case_study_v1.yaml`
