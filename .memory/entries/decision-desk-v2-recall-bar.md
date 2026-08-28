---
id: decision-desk-v2-recall-bar
type: decision
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: NVIDIA gold cue-recall bar locked at 100% before catalog close
node_label: cue recall bar
tags: decision,desk,claims,trees,nvidia,recall,august-2026
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-08-27T19:10:00+00:00'
updated_at: '2026-08-27T19:10:00+00:00'
---
Pre-registered before the catalog close, not after seeing
the rebuilt rates. Fine-tune stays gated. A thin 13-tree
first cut is not the completeness net.

## Bar
metric `desk_cue_recall`. Split
`nvda-gold-20q-fy2022q2-fy2027q1`. Window 20q. Criterion
`1.0`. Source `scripts/_desk_trees_v2_recall.py` over NVDA
`novelty_view` only.

Every verified in-window excerpt that matches a promise or
goal cue, after explicit reject tags, must already live on
a typed tree as a seed or a later node. Misses are typed
from `novelty_view`. No `transcripts_raw`. No new LLM.

## Reject tags (not desk objects)
Rhetoric and process talk. Printed near-term dollar
guidance. Environment forecasts and guesses. TAM-only
market-size talk with no dated NVIDIA object.

Silent plus clock due stays slipped, not missed. Goals
never enter trust. Stamp stays `2026-08-27T18:02:00+00:00`.
Not mixed into the 17 Aug Rank IC book.
