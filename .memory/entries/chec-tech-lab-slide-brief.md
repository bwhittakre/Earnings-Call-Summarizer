---
id: chec-tech-lab-slide-brief
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-tech-lab-v2
title: Slide-prep brief — tech Rank IC case study (quote only these splits)
node_label: Slide brief
tags: checkpoint,rank-ic,lab,tech,slides,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-18T18:20:00+00:00'
updated_at: '2026-08-18T18:20:00+00:00'
---
For the 1-hour slide prep. Quote the split in the same sentence as the
number. Do not promote. `production_v1` stays frozen. No
`company_period_holdout`. The 2021-Q2 cut is the midpoint of 40 ordered
`asof` / `0_56` periods, not an AI-era theme.

Book: 25 tickers, `generated_at=2026-08-17T17:28:40+00:00`.
Label / horizon: `asof` / `0_56`. Natural single-signal Rank IC
(raw `company_period`). Lab z-score blends are a different object.

## What is live (say this)

1. **Software competitive novelty vs level.** Late software_cloud
   novelty 0.135418 vs level -0.098642 (`expe-tech-lab-v7`, late
   2021-Q2..2026-Q1). Every LOO still beats level; worst is ADSK out
   0.097348. IBM is optional: software_pure late 0.133729 vs -0.094081,
   jk min 0.091842 ADSK (`expe-tech-lab-v6`). Early sleeve also beats
   (0.117970 vs 0.081272, `expe-tech-lab-v4` / v7) but early LOO vs
   level fails on CRM.

1b. **Late software change vs level** is live on the 7-name
   software_cloud sleeve. 0.074131 vs -0.098642; every LOO positive
   and beats level; worst is MSFT out 0.022885 (`expe-tech-lab-v8`).
   IBM out is 0.080003. It is **not** IBM-optional the way novelty is:
   software_pure sleeve 0.080003 vs -0.094081 still beats level in
   every LOO, but MSFT out is -0.005035 (`expe-tech-lab-v9`).
   On late software, the live fact is “not moat/level,” not “novelty
   only.”

2. **Late hardware confidence.** Late semis_cycle confidence 0.113852
   vs change -0.057385; jk min 0.049743 MU; NVDA out 0.0909
   (`expe-tech-lab-v6`). Late designers (same names minus equipment)
   0.176083 vs change -0.078930; jk min 0.115598 MU; NVDA out 0.156875
   (`expe-tech-lab-v7`). Equipment diluted; it did not carry. Every
   leave-one-period mean stays positive; dropping 2023-Q3 (the fattest
   up-quarter) leaves 0.138734 (`expe-tech-lab-v9`).

## What is not live (say this)

- Novelty is **not** uniquely better than change after every name drop.
  Sleeve novelty 0.135418 vs change 0.074131, but CRM out and ADSK out
  flip by 2–5 bps (`expe-tech-lab-v7`).
- Late **tech_core** competitive change lost to moat (0.074872 vs
  0.085099, `expe-tech-lab-v5`). Late 22-name change still beat
  (0.103985 vs 0.080684, `expe-tech-lab-v4`); that beat is a
  services-group residual (drop ACN or CTSH or IBM alone keeps it;
  drop all three flips it, `expe-tech-lab-v6`).
- Late **core** confidence is dead (jk min -0.004687 NVDA out,
  `expe-tech-lab-v5`).
- Software confidence is a negative control: +0.078 early / -0.090 late
  (`expe-tech-lab-v4`).
- Demand inversion is early-only. Late semis demand quant 0.064848
  beats level 0.036670 (`expe-tech-lab-v5`).

## What not to say

- Do not recycle morning kitchen-sink `equal_call_date` / `narrative_only`.
- Do not call the midpoint an AI-era cut.
- Do not put confidence on the software sleeve.
- One recipe = one dimension. No cross-dimension blend as a “tech score.”
