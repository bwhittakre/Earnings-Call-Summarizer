---
id: expe-term-structure-v2
type: experiment
project: earnings-call-summarizer
parent_id: plan-term-structure
title: Pre-register name-robustness of combined-window premium and early dilution
node_label: Term structure v2
tags: experiment,rank-ic,lab,horizon,term-structure,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-18T18:50:00+00:00'
updated_at: '2026-08-18T18:55:00+00:00'
---
Pre-registered **before** leave-one-out tests of the v1 combined-window
facts. Sleeve means from `expe-term-structure-v1` stay locked and are
not reused as jackknife wins.

## Locked
- Same book, label, sleeves, early/late lists as v1
- Natural single-signal Rank IC

## Line 1 — late combined-window premium is name-robust
On late software_cloud competitive novelty, every leave-one-out:
`0_56` mean > that fold's `0_14` AND > `14_35` AND > `35_56`.

## Line 2 — early novelty is a print that 0_56 dilutes, name-robust
On early software_cloud competitive novelty, every leave-one-out:
`0_14` mean > that fold's `0_56`.

## Line 3 — stretching helps late designer confidence, name-robust
On late designers / management_confidence `llm_level`, every
leave-one-out: `0_90` mean > 0.

## Pass criterion
Lines 1, 2, and 3 all hold on split `asof-term-structure-17aug-book-v2`.

## Null interpretation
The combined-window premium or early dilution is one name, or late
designer 0_90 is one name. Do not promote.

## Verdict
**Fail** on split `asof-term-structure-17aug-book-v2`
(`generated_at=2026-08-17T17:28:40+00:00`). Source:
`scripts/_term_structure_v2.py`. Lines 2 and 3 passed. Line 1 failed.

Line 1: ADSK out late 0_56 0.097348 < 14_35 0.113739. INTU out late
0_56 0.137051 < 0_14 0.167237. The combined-window premium is a
7-name fact, not a jackknife fact.

Line 2: every early LOO keeps 0_14 > 0_56. Early novelty is a print
that the combined window dilutes, name-robust.

Line 3: late designer 0_90 stays positive after every name drop.
Worst is MU out 0.112057. NVDA out 0.208943.

Not a promotion.
