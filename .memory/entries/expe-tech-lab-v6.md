---
id: expe-tech-lab-v6
type: experiment
project: earnings-call-summarizer
parent_id: plan-tech-lab-v2
title: Pre-register depth on software novelty and late semis confidence
node_label: Tech Lab v6
tags: experiment,rank-ic,lab,tech,pre-registered,august-2026
status: active
open_threads: 0
success: 'true'
files: ''
created_at: '2026-08-18T18:00:00+00:00'
updated_at: '2026-08-18T18:00:00+00:00'
---
Pre-registered **before** v6 ICs were computed. v3–v5 stay locked.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`
- Label / horizon: `asof` / `0_56`
- Early / late: v4 lists (2016-Q2..2021-Q1 / 2021-Q2..2026-Q1)
- Natural single-signal Rank IC. No new weights. production_v1 stays frozen.

## Line 1 — software_pure late (the live object without IBM)
On late 20 periods, software_pure competitive `narrative_novelty`:
1. IC > 0
2. IC > `llm_level` on the same names / periods
3. every leave-one-out IC > 0
4. every leave-one-out IC > that fold's level

## Line 2 — late semis confidence (the unclosed candidate)
On late 20 periods, semis_cycle management_confidence `llm_level`:
1. every leave-one-out IC > 0
2. every leave-one-out IC > that fold's `change_magnitude`

## Diagnostic (not in the pass bar)
Late 22-name competitive change vs level after dropping each of
ACN / CTSH / IBM one at a time. Already know dropping all three loses
(`expe-tech-lab-v5`). This only asks which name flips the beat.

Period Rank IC series for software_cloud novelty vs level (descriptive).

## Pass criterion
Lines 1 and 2 both hold on split `asof-0_56-17aug-book-v6`.

## Null interpretation
Software novelty late needs IBM in the sleeve, or late semis confidence
is a one-name artifact. Do not promote either.

## Verdict
**Pass.** Both lines held on split `asof-0_56-17aug-book-v6`
(`generated_at=2026-08-17T17:28:40+00:00`). Source: `scripts/_tech_lab_v6.py`.

Line 1: software_pure late novelty 0.133729 vs level -0.094081. Jackknife
min 0.091842 (ADSK out), 6/6 folds beat level.

Line 2: semis_cycle late confidence 0.113852 vs change -0.057385.
Jackknife min 0.049743 (MU out). NVDA out is 0.0909 — not the fragile
name. 10/10 folds beat change.

Diagnostic: dropping ACN or CTSH or IBM alone keeps late 22-name change
above level. Only dropping all three (v5 tech_core) flips the beat.

Period series (descriptive): late novelty &gt; 0 in 13/20 periods and
beats level in 14/20. Not a single-quarter spike.

Not a promotion.

