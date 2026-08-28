---
id: expe-path-id-v1
type: experiment
project: earnings-call-summarizer
parent_id: plan-path-id
title: Pre-register Path ID L1–L3 on the 17 Aug book
node_label: Path ID v1
tags: experiment,rank-ic,lab,path-id,term-structure,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-26T16:17:00+00:00'
updated_at: '2026-08-26T16:30:00+00:00'
results:
  - metric: case_study_pass
    value: 0
    unit: bool
    split: asof-path-id-17aug-book-v1
    window: late-2021Q2-2026Q1
    criterion: all three lines
    source: scripts/_path_id_v1.py
  - metric: mean_path_ic_14_35
    value: -0.054335
    split: asof-path-id-17aug-book-v1
    window: late-20-periods
    criterion: '> mean_novelty_ic_14_35'
    source: path_id_v1
  - metric: mean_novelty_ic_14_35
    value: 0.082817
    split: asof-path-id-17aug-book-v1
    window: late-20-periods
    source: path_id_v1
  - metric: l1_pass
    value: 0
    unit: bool
    split: asof-path-id-17aug-book-v1
    criterion: path IC > novelty IC, both finite >=15/20
    source: path_id_v1
  - metric: hit_rate
    value: 0.457143
    split: asof-path-id-17aug-book-v1
    window: 140-name-quarters
    criterion: '>=0.45'
    source: path_id_v1
  - metric: l2_pass
    value: 1
    unit: bool
    split: asof-path-id-17aug-book-v1
    criterion: hit_rate>=0.45
    source: path_id_v1
  - metric: l3_periods_finite
    value: 0
    split: asof-path-id-17aug-book-v1
    window: late-20-periods
    criterion: '>=15'
    source: path_id_v1
  - metric: l3_pass
    value: 0
    unit: bool
    split: asof-path-id-17aug-book-v1
    criterion: subset IC > full IC, both defined >=15 periods
    source: path_id_v1
  - metric: front_vs_later_hit_rate
    value: 0.7
    split: asof-path-id-17aug-book-v1
    criterion: diagnostic-only
    source: path_id_v1
---
Pre-registered **before** period Path ID ICs or hit rates were
computed. v1–v3 sleeve means stay locked and are not reused as
confirmatory wins.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`
- Label: `asof`
- Late: v4 list (2021-Q2..2026-Q1)
- Sleeve: `software_cloud` / competitive_position / `narrative_novelty`
- Natural Rank IC. `production_v1` stays frozen.
- Live features may use call-date novelty and realized `0_14`
  `label_mean` only. Ex-post argmax of the three buckets scores
  Line 2 only.

## Line 1 — first print changes the later-bucket bet
`path_signal = z(novelty) * (+1 if 0_14 return is not in the period
top tercile else -1)`.
Top tercile = highest `ceil(n/3)` names that period.

Bar: mean period Spearman of `path_signal` vs `14_35` return **>**
mean period Spearman of raw novelty vs `14_35` return, same late
software names/periods, both ICs finite in ≥15 of 20 late periods.

## Line 2 — predicted path is identifiable at T+14
Rule: top tercile `0_14` → predict `0_14`; else if novelty ≥ period
median → predict `14_35`; else predict `35_56`. Ex-post winner =
argmax of the three bucket returns (ties dropped).

Bar: hit rate ≥ 0.45 on late software name-quarters with all three
buckets. Binary front-vs-later is a diagnostic, not a pass line.

## Line 3 — the path is the ranking object
On names predicted later (not top `0_14` tercile), novelty Rank IC
on `14_35` beats full-sleeve novelty Rank IC on `14_35`. Mean of
period ICs. Require ≥5 names in both the subset and the full sleeve
for a period to count.

Bar: mean subset IC **>** mean full-sleeve IC, both defined on ≥15
late periods.

## Pass criterion
Lines 1, 2, and 3 all hold on split `asof-path-id-17aug-book-v1`.

## Null interpretation
The first print is noise and Path ID is not live. Do not promote a
single line.

## Diagnostic only
Jackknife drop ADSK and drop INTU on Line 1. core22 demand /
`quant_z_pit` may be printed as a contrast, not a confirmatory object.

## Verdict
**Fail** on split `asof-path-id-17aug-book-v1`
(`generated_at=2026-08-17T17:28:40+00:00`). Source:
`scripts/_path_id_v1.py`. Line 2 passed. Lines 1 and 3 failed.
Do not promote a single line. Path ID is not live.

Line 1: mean path IC vs `14_35` is **-0.054335** vs raw novelty
**0.082817** on 20/20 late periods. The first-print sign flip
does not improve the later-bucket bet.

Line 2: hit rate **0.457143** (64/140) ≥ 0.45. Predicted path
at T+14 is identifiable at the pre-registered bar. Binary
front-vs-later hit rate 0.7 is diagnostic only.

Line 3: **0** late periods with both subset and full-sleeve ICs
defined. Predicted-later names are 4 of 7 on this sleeve; the
bar requires ≥5 names. Unreachable here, not a retune.

Jackknife (diagnostic): drop ADSK path IC -0.092447 vs novelty
0.113739; drop INTU path IC 0.054953 vs novelty 0.069025.
Neither flips Line 1.

Roz earned a read-only Lab panel because one confirmatory line
passed. No production-pack write. No healthcare mix.
