---
id: expe-horizon-anatomy-v1
type: experiment
project: earnings-call-summarizer
parent_id: plan-horizon-anatomy
title: Pre-register horizon anatomy of prints vs live objects
node_label: Horizon v1
tags: experiment,rank-ic,lab,horizon,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-18T18:22:00+00:00'
updated_at: '2026-08-18T18:28:00+00:00'
---
Pre-registered **before** any non-`0_56` Rank ICs were computed.
Tech v1–v9 stay locked and are not reused as confirmatory wins.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`
- Label: `asof`
- Horizons: `0_14` (T+7 to T+21), `14_35` (T+22 to T+42),
  `35_56` (T+43 to T+63). `0_56` is a reference only.
- Universe: core22 = book minus OPAL/SPCX/STRW (a priori odd names)
- Sleeves: `software_cloud`, `designers` (existing lists)
- Late periods: v4 list (2021-Q2..2026-Q1)
- Natural single-signal Rank IC. No Lab z. production_v1 stays frozen.

## Line 1 — prints are front-loaded
On core22, mean period Rank IC on `0_14` > same signal on `35_56` for both:
1. demand / `quant_z_pit` (production primary)
2. guidance / `surprise_magnitude`

## Line 2 — software novelty is not a T+7 pop
On software_cloud / competitive_position / `narrative_novelty`:
1. `0_14` IC > 0 and > `llm_level` on `0_14`
2. `35_56` IC > 0 and > `llm_level` on `35_56`

## Line 3 — late designer confidence is not a T+7 pop
On late designers / management_confidence / `llm_level`:
1. `35_56` IC > 0
2. `35_56` IC > `change_magnitude` on the same late `35_56` rows

## Diagnostic (not in the pass bar)
- `14_35` for every confirmatory cell
- `0_56` reference on the same names (known from tech thread; not a win)
- core22 competitive `change_magnitude` `0_14` vs `35_56`

## Pass criterion
Lines 1, 2, and 3 all hold on split `asof-horizon-anatomy-17aug-book-v1`.

## Null interpretation
The combined `0_56` means are horizon-flat, or the live objects are
front-loaded prints. Do not promote. Do not treat a `0_56` object as
surviving the late bucket unless Line 2 / 3 say so.

## Verdict
**Fail** on split `asof-horizon-anatomy-17aug-book-v1`
(`generated_at=2026-08-17T17:28:40+00:00`). Source:
`scripts/_horizon_anatomy_v1.py`. Line 1 failed. Lines 2 and 3 passed.

Line 1: guidance surprise is front-loaded (0_14 0.050003 > 35_56 0.035452,
40 periods, core22). Demand quant is not: 0_14 -0.007152 < 35_56 0.014354.
Demand quant peaks in the mid bucket (14_35 0.045755). The production
primary is not a T+7 print.

Line 2: software novelty 0_14 0.126509 vs level -0.056907; 35_56 0.070562
vs -0.079985. Both buckets positive and beat level. Diagnostic: 14_35
novelty 0.026608 **loses** to level 0.106195. The 0_56 mean 0.126694
mixes a strong front, a mid-window hole, and a still-positive back.

Line 3: late designer confidence is back-loaded. 35_56 0.191130 vs change
0.132232. Front bucket is negative (0_14 -0.098494). 14_35 0.110109.
The 0_56 0.176083 is carried by the late window, not a T+7 pop.

Diagnostic: core22 competitive change 0_14 0.099170, 14_35 -0.021096,
35_56 0.085938. Same mid-window hole as software novelty.

Not a promotion. Name-robustness of the two passing lines is not in
this bar.
