---
id: expe-tech-lab-v9
type: experiment
project: earnings-call-summarizer
parent_id: plan-tech-lab-v2
title: Pre-register IBM-optional late software change and designer period-drop
node_label: Tech Lab v9
tags: experiment,rank-ic,lab,tech,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-18T18:30:00+00:00'
updated_at: '2026-08-18T18:35:00+00:00'
---
Pre-registered **before** v9 ICs were computed. v3–v8 stay locked.
v8 passed late software_cloud change vs level (jk min 0.022885 MSFT).
That sleeve includes IBM. The 14/20 designer period count is
descriptive only and is not reused as a win.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`
- Label / horizon: `asof` / `0_56`
- Late: v4 list (2021-Q2..2026-Q1)
- Natural single-signal Rank IC. production_v1 stays frozen.

## Line 1 — late software change does not need IBM
On late software_pure / competitive_position `change_magnitude`:
1. IC > 0
2. IC > `llm_level`
3. every leave-one-out IC > 0
4. every leave-one-out IC > that fold's level

## Line 2 — late designer confidence mean is not one quarter
On late designers / management_confidence `llm_level`:
every leave-one-period-out mean IC > 0.

## Pass criterion
Lines 1 and 2 both hold on split `asof-0_56-17aug-book-v9`.

## Null interpretation
Late software change vs level needs IBM, or the designer mean is a
single-quarter spike. Do not promote.

## Verdict
**Fail** on split `asof-0_56-17aug-book-v9`
(`generated_at=2026-08-17T17:28:40+00:00`). Source: `scripts/_tech_lab_v9.py`.
Line 2 passed. Line 1 failed the all-LOO-positive bar.

Line 1 sleeve: software_pure late change 0.080003 vs level -0.094081.
Every LOO still beats level. MSFT out is -0.005035 vs level -0.148909 —
sign flips, uniqueness-vs-level does not. Other folds stay positive
(ORCL 0.023575 is the next tightest). Contrast v8 software_cloud
(MSFT out +0.022885): IBM kept that fold above zero. Do not call late
software change IBM-optional the way novelty is (`expe-tech-lab-v6`).

Line 2: every leave-one-period mean of late designer confidence stays
positive. Worst is dropping 2023-Q3 (the +0.885714 spike); remaining
mean is 0.138734. Not a one-quarter object.

Not a promotion.
