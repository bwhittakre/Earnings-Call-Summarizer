---
id: expe-term-structure-v3
type: experiment
project: earnings-call-summarizer
parent_id: plan-term-structure
title: Pre-register why late 0_56 beats every bucket — period premium and noise cancellation
node_label: Term structure v3
tags: experiment,rank-ic,lab,horizon,term-structure,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-18T18:55:00+00:00'
updated_at: '2026-08-18T19:05:00+00:00'
---
Pre-registered **before** period-level late ICs and bucket-return
correlations were computed. v1 sleeve means and v2 jackknife stay locked
and are not reused as confirmatory wins.

Call-date `narrative_novelty` is the same number in every horizon. Only
the forward specific-return label changes. `0_56` compounds the three
tiled buckets (`Structured Narrative/asof_alpha.py`). Spearman of a
compound is not the average of the three Spearmans.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`
- Label: `asof`
- Late: v4 list (2021-Q2..2026-Q1)
- Sleeve: `software_cloud` / competitive_position / `narrative_novelty`
- Natural Rank IC. production_v1 stays frozen.

## Line 1 — the premium is a typical late quarter
In ≥ 12 of 20 late periods with all four ICs finite:
IC(`0_56`) > max(IC(`0_14`), IC(`14_35`), IC(`35_56`)).

## Line 2 — the buckets are different return rankings
Mean of the three pairwise Spearmans of **bucket returns** (not the
signal), averaged across late periods with all three pairs finite, is
< 0.50.

## Line 3 — averaging noisy slice returns recovers a premium
Mean period IC of novelty vs the equal-weight z-sum of the three
bucket returns > the mean of the three bucket ICs (same names / periods).
That is the noise-cancellation mechanism: average the returns, not the ICs.

## Pass criterion
Lines 1, 2, and 3 all hold on split `asof-term-structure-17aug-book-v3`.

## Null interpretation
The late `0_56` premium is a few-quarter mean artifact, or the buckets
are the same bet, or compounding does something averaging cannot.
Do not promote.

## Verdict
**Fail** on split `asof-term-structure-17aug-book-v3`
(`generated_at=2026-08-17T17:28:40+00:00`). Source:
`scripts/_term_structure_v3.py`. Lines 2 and 3 passed. Line 1 failed.

Line 1: period-level premium in **4/20** late quarters (2022-Q3,
2022-Q4, 2025-Q1, 2026-Q1). The sleeve mean 0_56 0.135418 >
every bucket mean is not a typical-quarter fact.

Line 2: mean pairwise Spearman of the three bucket **returns** is
0.052381. The slices are nearly uncorrelated rankings — different bets.

Line 3: novelty vs z-sum of the three bucket returns has mean IC
0.158035, above the mean of the three bucket ICs (0.060493) and
above 0_56 itself (0.135418). Averaging the noisy slice returns
recovers the premium. Compounding is not doing extra work beyond
that cancellation.

The 0_56-over-bucket mean is what you get when you Spearman a
compound of uncorrelated noisy slices and then average those
period ICs. Most late quarters still have some bucket beating 0_56.
Not a promotion.
