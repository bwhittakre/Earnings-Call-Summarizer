---
id: checkpoint-desk-hc-first-seeds
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: Healthcare claims-desk book and first seeds
tags: checkpoint,desk,claims,healthcare,august-2026
created_at: 2026-08-31T14:50:00+00:00
updated_at: 2026-08-31T14:50:00+00:00
---
Healthcare is on the claims desk as a sibling book. NVIDIA gold
and the tech ops stamp stay locked.

Gold remains `desk_trees_v2.json` stamp `2026-08-27T18:02:00+00:00`.
Tech ops remains `desk_trees_ops_v2.json` stamp
`2026-08-31T14:18:00+00:00`. Healthcare is
`desk_trees_hc_v2.json` stamp `2026-08-31T14:45:00+00:00`,
book `desk_hc_v2`, split `hc-ops-novelty-present`.

Universe is the 20 `healthcare_large_cap` names with
`novelty_view`. Scan writes `desk_cue_queue_v2_<TICKER>.json`
with the healthcare stamp so leftovers do not leak into the
tech ops queue. Roz Claims Trees now has three books:
`nvda_gold_v2`, `desk_ops_v2`, `desk_hc_v2`.

First seeds: 20 hand-typed trees, one per name, from leftover
novelty excerpts. Delivered, hit, and missed were not invented.
After rescan every name has `n_covered: 1`.

Dry walk LLY FY2026-Q2: walked the healthcare book only.
Gold and tech ops file bytes unchanged.

Rank IC / `production_v1` / the 17 Aug book were not mixed.
No commit in this pass.
