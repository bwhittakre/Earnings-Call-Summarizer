---
id: note-novelty-dimension-coverage
type: note
project: earnings-call-summarizer
parent_id: expe-tech-lab-case-study
title: narrative_novelty is only scored on three dimensions in the 17 Aug book
node_label: Novelty coverage
tags: note,rank-ic,novelty,coverage,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-18T15:45:00+00:00'
updated_at: '2026-08-18T15:45:00+00:00'
---
On `asof` / `0_56` company_period rows from
`generated_at=2026-08-17T17:28:40+00:00`, `narrative_novelty` has 887 rows on
`competitive_position`, `macro_regulatory_risk`, and `management_confidence`
only. It is **absent** on `demand`, `margins`, `guidance`, and
`capital_allocation`.

`quant_guidance_revision_z_pit` is absent on every dimension.

Consequence: a Lab recipe that puts weight on novelty (or T+7 revision) on an
unscored dimension silently equals the remaining signals. H3 (AI capex on
capital_allocation) matched `llm_level` exactly for this reason — same class
of miss as this morning's `quant_plus_novelty` on demand.
