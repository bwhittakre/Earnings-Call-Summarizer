---
id: expe-tech-lab-case-study
type: experiment
project: earnings-call-summarizer
parent_id: plan-tech-lab-case-study
title: Pre-register tech Lab case study vs natural Rank IC
node_label: Tech case study
tags: experiment,rank-ic,lab,tech,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-18T15:30:00+00:00'
updated_at: '2026-08-18T15:30:00+00:00'
---
Pre-registered **before** case-study Rank ICs were computed.

## Hypothesis
At least 3 of the 7 story recipes in `tech_lab_v1` have a higher mean period
Rank IC than their named natural baseline on `asof` / `0_56` over the 17 Aug
book (`generated_at=2026-08-17T17:28:40+00:00`), using the same-window overlap
as `expe-lab-vs-production`. `H8` is a control and is excluded from the count.

## Pass criterion
`story_beats >= 3` on split `asof-0_56-17aug-book-same-window`.

## Null interpretation
Tech-story blends do not systematically beat the natural single-signal Rank IC
on this book. Keep exploring stories; do not promote any recipe to production.

## Verdict
**Fail.** `story_beats=2` of 7 on split `asof-0_56-17aug-book-same-window`
(`generated_at=2026-08-17T17:28:40+00:00`). Source:
`scripts/_tech_lab_case_study.py`.

| id | lab IC | natural | delta | beat |
|---|---|---|---|---|
| H1 semi surprise | 0.003401 | 0.023569 | -0.020168 | no |
| H2 software guidance | 0.011002 | 0.027237 | -0.016235 | no |
| H3 AI capex | -0.013991 | -0.013991 | 0.0 | no (novelty missing) |
| H4 share-shift | 0.069028 | 0.053878 | +0.015150 | yes |
| H5 software margins | -0.010514 | -0.062213 | +0.051699 | yes (still negative) |
| H6 export residual | -0.069785 | -0.059074 | -0.010711 | no |
| H7 conviction change | -0.011506 | 0.032986 | -0.044492 | no |
| H8 demand control | 0.019053 | 0.028393 | -0.009340 | no (excluded) |

Live finding: H4. Coverage gotcha: `narrative_novelty` is only populated on
competitive_position, macro_regulatory_risk, and management_confidence.
`quant_guidance_revision_z_pit` is empty. Not a promotion.
