---
id: expe-tech-lab-v8
type: experiment
project: earnings-call-summarizer
parent_id: plan-tech-lab-v2
title: Pre-register late software change as its own object, plus designer period series
node_label: Tech Lab v8
tags: experiment,rank-ic,lab,tech,pre-registered,august-2026
status: active
open_threads: 0
success: 'true'
files: ''
created_at: '2026-08-18T18:22:00+00:00'
updated_at: '2026-08-18T18:28:00+00:00'
---
Pre-registered **before** v8 ICs were computed. v3–v7 stay locked.
v7 showed late software change beats level on the sleeve (0.074131 vs
-0.098642) but that number is not a jackknife result and is not reused
as a win.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`
- Label / horizon: `asof` / `0_56`
- Late: v4 list (2021-Q2..2026-Q1)
- Natural single-signal Rank IC. production_v1 stays frozen.

## Line 1 — late software change is itself a live object vs level
On late software_cloud / competitive_position `change_magnitude`:
1. IC > 0
2. IC > `llm_level`
3. every leave-one-out IC > 0
4. every leave-one-out IC > that fold's level

## Diagnostic (not in the pass bar)
Period Rank IC series for late designers / management_confidence
`llm_level` (count of periods > 0). Descriptive only.

## Pass criterion
Line 1 holds on split `asof-0_56-17aug-book-v8`.

## Null interpretation
Late software competitive edge vs level is novelty-only; change does
not survive names. Do not promote.

## Verdict
**Pass** on split `asof-0_56-17aug-book-v8`
(`generated_at=2026-08-17T17:28:40+00:00`). Source: `scripts/_tech_lab_v8.py`.

Line 1: late software_cloud change 0.074131 vs level -0.098642.
Jackknife min 0.022885 (MSFT out). 7/7 folds positive and beat level.
IBM out is 0.080003 — not an IBM object. Tightest fold is still above
zero and still beats a deeply negative level.

Diagnostic: late designers confidence Rank IC > 0 in 14/20 periods.
k=6 so tails are fat (2022-Q2 -0.927634; 2023-Q3 0.885714). The mean
is a walk-forward average across a majority of late quarters, not a
single spike. Period-drop robustness is not in this bar.

Together with v7: late software has two live competitive signals vs
level (novelty and change). Novelty is larger on the sleeve but not
uniquely better than change after CRM or ADSK. Not a promotion.
