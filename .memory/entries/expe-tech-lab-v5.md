---
id: expe-tech-lab-v5
type: experiment
project: earnings-call-summarizer
parent_id: plan-tech-lab-v2
title: Pre-register cleaner-book, late jackknife, and demand-inversion persistence
node_label: Tech Lab v5
tags: experiment,rank-ic,lab,tech,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-18T17:15:00+00:00'
updated_at: '2026-08-18T17:15:00+00:00'
---
Pre-registered **before** v5 ICs were computed. v3/v4 results stay locked.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`
- Label / horizon: `asof` / `0_56`
- Early / late: the v4 lists (2016-Q2..2021-Q1 / 2021-Q2..2026-Q1)
- `tech_core` (19): book minus OPAL/SPCX/STRW and minus ACN/CTSH/IBM.
  Services dropped because they are not the tech thesis, **not** because
  CTSH was the v3 worst leave-one-out.
- Natural single-signal Rank IC. production_v1 stays frozen.

## Line 1 — live objects on tech_core
Object A holds if competitive `change_magnitude` > 0 and > `llm_level` on
`tech_core` for **full, early, and late**, and software_cloud novelty > 0
and > level for **full, early, and late**.

Object B holds if management_confidence `llm_level` > 0 and >
`change_magnitude` on `tech_core` for **full, early, and late**, and
semis_cycle confidence level > 0 for **full, early, and late**.

## Line 2 — late-window jackknife of the v4 objects
On the **late** 20 periods only, leave-one-out:
1. 22-name core (minus odd names only) competitive change: every fold > 0
   and every fold > that fold's level
2. software_cloud novelty: every fold > 0 and every fold > that fold's level
3. 22-name core confidence level: every fold > 0 and every fold > that
   fold's change

## Line 3 — demand inversion (own object)
v2 found semis demand level and surprise beat quant. Persistence test:
1. semis demand `llm_level` > `quant_z_pit` on early AND late
2. semis demand `surprise_magnitude` > `quant_z_pit` on early AND late
3. full-window jackknife: every LOO of semis demand level still beats that
   LOO's quant

## Pass criterion
Lines 1 and 2 both hold on split `asof-0_56-17aug-book-v5`. Line 3 is a
separate hold / fail and does not sink Lines 1–2.

## Null interpretation
The live objects are a services residual, a late-window one-name artifact,
or both. The demand inversion is an era or one-name artifact if Line 3
fails. Do not promote.

## Verdict
**Fail** on split `asof-0_56-17aug-book-v5`
(`generated_at=2026-08-17T17:28:40+00:00`). Source: `scripts/_tech_lab_v5.py`.
`case_study_pass=false` (Lines 1 and 2). Line 3 also failed.

Line 1: late tech_core competitive change 0.074872 lost to level 0.085099.
Full and early still beat. Software novelty still beats in all three windows.

Line 2: late 22-name confidence jackknife min -0.004687 (NVDA out); MU out
-0.0038 and loses to change. Late change and late software novelty
jackknives both held (change min 0.085331 ADBE out; novelty min 0.097348
ADSK out).

Line 3: early semis demand level 0.088031 and surprise 0.048639 beat quant
-0.018182. Late quant 0.064848 beats level 0.036670 and surprise 0.037469.
Full-window level-vs-quant jackknife fails only on NVDA (0.021509 vs
0.039596).

Not a promotion. The object that survives every cut is software
competitive novelty.

