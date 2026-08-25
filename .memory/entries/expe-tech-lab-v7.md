---
id: expe-tech-lab-v7
type: experiment
project: earnings-call-summarizer
parent_id: plan-tech-lab-v2
title: Pre-register uniqueness of software novelty and late designer confidence
node_label: Tech Lab v7
tags: experiment,rank-ic,lab,tech,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-18T18:10:00+00:00'
updated_at: '2026-08-18T18:20:00+00:00'
---
Pre-registered **before** v7 ICs were computed. v3–v6 stay locked.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`
- Label / horizon: `asof` / `0_56`
- Late: v4 list (2021-Q2..2026-Q1). Early: 2016-Q2..2021-Q1.
- Natural single-signal Rank IC. production_v1 stays frozen.

## Line 1 — novelty is the software object, not competitive change
On late software_cloud / competitive_position:
1. `narrative_novelty` > `change_magnitude`
2. `narrative_novelty` > `llm_level` (replication of v4/v6)
3. every leave-one-out: novelty > that fold's change
4. every leave-one-out: novelty > that fold's level

## Line 2 — late confidence is a hardware fact, not only a semis-cycle fact
On late designers / management_confidence `llm_level`:
1. IC > 0
2. IC > `change_magnitude`
3. every leave-one-out IC > 0
4. every leave-one-out IC > that fold's change

## Diagnostic (not in the pass bar)
- Late software_cloud change vs level (is change also live?)
- Early software_cloud novelty jackknife vs level (symmetry with v5/v6 late)

## Pass criterion
Lines 1 and 2 both hold on split `asof-0_56-17aug-book-v7`.

## Null interpretation
Late software edge is generic competitive signal, or late confidence
does not replicate in designers (k=6). Do not promote.

## Verdict
**Fail** on split `asof-0_56-17aug-book-v7`
(`generated_at=2026-08-17T17:28:40+00:00`). Source: `scripts/_tech_lab_v7.py`.
Line 2 passed. Line 1 failed the jackknife-vs-change uniqueness bar.

Line 1 sleeve: late software_cloud novelty 0.135418 vs change 0.074131
vs level -0.098642. Novelty beats both on the sleeve. Every LOO novelty
beats that fold's level (min 0.097348 ADSK out). Uniqueness vs change
fails on two folds: CRM out novelty 0.128809 vs change 0.130787
(delta -0.001978); ADSK out 0.097348 vs 0.102285 (delta -0.004937).
Do not claim novelty is uniquely better than change after every name drop.

Line 2: late designers confidence 0.176083 vs change -0.078930.
Jackknife min 0.115598 (MU out). NVDA out is 0.156875. 6/6 folds
positive and beat change. Stronger than late semis_cycle +0.114 in
`expe-tech-lab-v6` — equipment was diluting, not carrying.

Diagnostic: late software change also beats level (0.074131 vs -0.098642).
Early novelty 0.117970 vs level 0.081272 on the sleeve; jackknife vs
level fails on CRM out (0.048944 vs 0.150334). Late uniqueness vs level
is tighter than early.

Not a promotion.
