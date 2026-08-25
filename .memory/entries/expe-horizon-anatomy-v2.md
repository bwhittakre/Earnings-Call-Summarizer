---
id: expe-horizon-anatomy-v2
type: experiment
project: earnings-call-summarizer
parent_id: plan-horizon-anatomy
title: Pre-register name-robustness of the two horizon-surviving objects
node_label: Horizon v2
tags: experiment,rank-ic,lab,horizon,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-18T18:28:00+00:00'
updated_at: '2026-08-18T18:35:00+00:00'
---
Pre-registered **before** leave-one-out ICs on non-`0_56` horizons were
computed. v1 results stay locked and are not reused as jackknife wins.

## Locked
- Same book, label, sleeves, late list as `expe-horizon-anatomy-v1`
- Horizons under test: `35_56` only for the confirmatory lines
- Natural single-signal Rank IC

## Line 1 — software novelty late-bucket jackknife
On software_cloud / competitive_position, horizon `35_56`, all 40 periods:
1. every leave-one-out novelty IC > 0
2. every leave-one-out novelty IC > that fold's `llm_level`

## Line 2 — late designer confidence late-bucket jackknife
On late designers / management_confidence, horizon `35_56`:
1. every leave-one-out level IC > 0
2. every leave-one-out level IC > that fold's `change_magnitude`

## Diagnostic (not in the pass bar)
software_cloud novelty vs level on `14_35` (v1 sleeve lost). Descriptive.

## Pass criterion
Lines 1 and 2 both hold on split `asof-horizon-anatomy-17aug-book-v2`.

## Null interpretation
The late-bucket objects are one-name artifacts. Do not promote.

## Verdict
**Fail** on split `asof-horizon-anatomy-17aug-book-v2`
(`generated_at=2026-08-17T17:28:40+00:00`). Source:
`scripts/_horizon_anatomy_v2.py`. Line 1 passed. Line 2 failed
level-over-change uniqueness.

Line 1: software novelty 35_56 0.070562 vs level -0.079985. Jackknife
min 0.025389 (IBM out). 7/7 folds positive and beat level.

Line 2: late designer confidence 35_56 0.191130 vs change 0.132232.
Every LOO stays positive (min 0.129893 AMD out). AMD out loses to
change (0.129893 vs 0.207672). The late-bucket sign is name-robust;
the cheap-talk beat is AMD-dependent.

Diagnostic: 14_35 novelty 0.026608 still loses to level 0.106195
(replication of v1 sleeve).

Not a promotion.
