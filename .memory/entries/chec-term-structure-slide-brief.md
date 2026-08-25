---
id: chec-term-structure-slide-brief
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-term-structure
title: Slide-prep brief — Rank IC term structure (quote only these splits)
node_label: Term-structure brief
tags: checkpoint,rank-ic,lab,horizon,slides,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-18T18:50:00+00:00'
updated_at: '2026-08-18T18:50:00+00:00'
---
Third case study. Same 17 Aug book, `asof`,
`generated_at=2026-08-17T17:28:40+00:00`. Do not promote.
`0_56` is a combined return (T+7 to T+63), not an average of
`0_14` / `14_35` / `35_56`.

## The sentence that wows

The full-sample software-novelty U-shape is an **average of two
different curves**. Early (2016-Q2..2021-Q1): 0.183 / −0.030 / 0.112
(U). Late (2021-Q2..2026-Q1): 0.070 / 0.083 / 0.029 (mid-hump).
Source: `expe-term-structure-v1`.

Late `0_56` novelty is 0.135418 — larger than every late bucket on
the 7-name sleeve. That premium dies if ADSK or INTU is held out
(`expe-term-structure-v2`). It is also **not a typical quarter**:
only 4/20 late periods have 0_56 IC > max(bucket ICs)
(2022-Q3, 2022-Q4, 2025-Q1, 2026-Q1). Bucket returns are nearly
uncorrelated (pairwise Spearman 0.052381). Novelty vs the z-sum of
the three bucket returns has mean IC 0.158035, above 0_56
(`expe-term-structure-v3`). The mean premium is noise cancellation
in the average, not a path most quarters take.

Early `0_56` 0.117970 is smaller than early `0_14` 0.183133 after
every name drop — early dilution is name-robust.

## What else to say

- Demand quant mid-hump is era-stable (early and late) but not the
  typical quarter (14/40). `expe-term-structure-v1`.
- Novelty U is not the typical quarter (15/40).
- Late designer confidence back-load **is** typical (17/20).
  `0_90` 0.217826 > `0_56` 0.176083 — stretching helps.
- Novelty `0_90` still beats level (0.070578 vs −0.027345) but
  dilutes vs `0_56`.
- Macro novelty and confidence novelty are not live on core22
  `0_56`.

## What not to say

- “Novelty is U-shaped” without naming the era.
- “0_56 is the average of the three buckets.”
- Promotion, holdout, AI-era. The 2021-Q2 cut is the midpoint of 40
  ordered periods.
