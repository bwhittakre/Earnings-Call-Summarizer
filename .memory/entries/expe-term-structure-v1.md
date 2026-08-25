---
id: expe-term-structure-v1
type: experiment
project: earnings-call-summarizer
parent_id: plan-term-structure
title: Pre-register term-structure persistence, concordance, and 0_90
node_label: Term structure v1
tags: experiment,rank-ic,lab,horizon,term-structure,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-18T18:40:00+00:00'
updated_at: '2026-08-18T18:50:00+00:00'
---
Pre-registered **before** era-split, period-concordance, `0_90`, and
unused-novelty ICs were computed. Horizon v1 full-window shapes stay
locked and are not reused as confirmatory wins.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`
- Label: `asof`
- Buckets: `0_14`, `14_35`, `35_56`. References: `0_56`, `0_90`
- Early / late: v4 lists (2016-Q2..2021-Q1 / 2021-Q2..2026-Q1)
- core22 = book minus OPAL/SPCX/STRW
- Sleeves: `software_cloud`, `designers`
- Natural single-signal Rank IC. production_v1 stays frozen.

## Shape definitions
- **mid-hump:** mean(14_35) > mean(0_14) AND mean(14_35) > mean(35_56)
- **U-shape:** mean(0_14) > mean(14_35) AND mean(35_56) > mean(14_35)
- Period U-shape: that period's 0_14 IC > 14_35 IC AND 35_56 IC > 14_35 IC
  (all three finite)

## Line A — v1 shapes persist in both eras (new split)
1. core22 demand / `quant_z_pit` is mid-hump in **early** and in **late**
2. software_cloud competitive `narrative_novelty` is U-shape in **early**
   and in **late**

## Line B — the U-shape is the typical quarter
On software_cloud competitive novelty, ≥ 20 of 40 periods with all three
bucket ICs finite are period-U-shaped.

## Line C — stretching the window does not kill novelty
software_cloud competitive novelty on `0_90`: IC > 0 and > `llm_level`
on `0_90`.

## Diagnostic (not in the pass bar)
- Demand quant mid-hump in ≥ 20/40 periods
- Late designer confidence: 35_56 > 0_14 in ≥ 12/20 late periods
- Demand quant `0_90` mean < `0_56` mean (dilution)
- core22 macro novelty `0_56` > 0 and > level
- core22 confidence novelty `0_56` > 0 and > level
- Full atlas (descriptive)

## Pass criterion
Lines A, B, and C all hold on split `asof-term-structure-17aug-book-v1`.

## Null interpretation
`0_56` means are averages of opposite curves, or the v1 shapes are
full-sample artifacts, or novelty dies when the window stretches.
Do not promote.

## Verdict
**Fail** on split `asof-term-structure-17aug-book-v1`
(`generated_at=2026-08-17T17:28:40+00:00`). Source:
`scripts/_term_structure_v1.py`. Line C passed. Lines A and B failed.

Line A: demand quant is mid-hump in both eras (early 0.019802 / 0.047832 /
0.030573; late -0.034106 / 0.043678 / -0.001866). Software novelty U
holds early (0.183133 / -0.029601 / 0.112347) and **flips late** to a
mid-hump (0.069885 / 0.082817 / 0.028776). The full-sample U
(0.126509 / 0.026608 / 0.070562) is an average of two different curves.

Line B: period U-shape in 15/40 quarters. The mean U is not the typical
quarter. Demand mid-hump is also not typical (14/40). Late designer
back-load is typical (17/20).

Line C: software novelty 0_90 0.070578 vs level -0.027345. Positive and
beats level. Diluted versus 0_56 0.126694.

Diagnostics: demand quant 0_90 0.002683 < 0_56 0.028622 (dilution).
Late designer 0_90 0.217826 > 0_56 0.176083 (stretching helps).
core22 macro novelty 0_56 -0.028370 (not live). core22 confidence
novelty 0.033248 loses to level 0.054965.

Late software novelty 0_56 0.135418 is **larger than every late
bucket**. Early 0_56 0.117970 is **smaller than early 0_14 0.183133**.
`0_56` is a different ranking object, not an average of the three
buckets. That premium/dilution is not in this bar.

Not a promotion.
