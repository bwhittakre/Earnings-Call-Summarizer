---
id: expe-tech-lab-v3
type: experiment
project: earnings-call-summarizer
parent_id: plan-tech-lab-v2
title: Pre-register stress test of two live Rank IC objects
node_label: Tech Lab v3
tags: experiment,rank-ic,lab,tech,jackknife,pre-registered,august-2026
status: active
open_threads: 0
success: 'true'
files: ''
created_at: '2026-08-18T16:05:00+00:00'
updated_at: '2026-08-18T16:05:00+00:00'
---
Pre-registered **before** v3 jackknife / drop-odd ICs were computed.
Point estimates from `expe-tech-lab-v2` are locked and are not re-used as
new wins. This run only asks whether those two objects survive a name
being removed.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`
- Label / horizon: `asof` / `0_56`
- Natural single-signal Rank IC (raw `company_period`, no Lab z)
- Odd names dropped as a group: OPAL, SPCX, STRW
- Jackknife = leave-one-ticker-out on the named sleeve, same periods as
  the full sleeve, `spearman_rank_ic` + `summarize_period_rank_ics`
- Software confidence is a **negative control** (already ≤ 0 in v2) and
  does not count toward Object B
- Designers confidence jackknife is reported, not confirmatory (k=6)
- No new weight fitting. production_v1 stays frozen

## Object A — competitive change (full book) and software novelty
Holds if **all** of:
1. `A_drop_odd_positive`: competitive `change_magnitude` Rank IC > 0 on
   the 22-name book (all minus OPAL/SPCX/STRW)
2. `A_drop_odd_beats_level`: that IC > competitive `llm_level` on the
   same 22 names / same periods
3. `A_jk_change_all_positive`: every leave-one-out IC of full-book
   competitive change is > 0
4. `A_jk_novelty_software_positive`: every leave-one-out IC of
   software_cloud competitive novelty is > 0
5. `A_jk_novelty_beats_level`: on every software_cloud leave-one-out
   sleeve, novelty IC > level IC (same remaining names, same periods)

## Object B — confidence level (full book and semis)
Holds if **all** of:
1. `B_drop_odd_positive`: management_confidence `llm_level` > 0 on the
   22-name book
2. `B_drop_odd_beats_change`: that IC > `change_magnitude` on the same
   22 names / same periods
3. `B_jk_all_positive`: every leave-one-out IC of full-book confidence
   level is > 0
4. `B_jk_semis_positive`: every leave-one-out IC of semis_cycle
   confidence level is > 0

## Pass criterion
Both objects hold on split `asof-0_56-17aug-book-jackknife`.

## Null interpretation
At least one “live” object is a one-name or odd-name artifact. Do not
treat it as a book fact. Do not promote.

## Verdict
**Pass.** Both objects held on split `asof-0_56-17aug-book-jackknife`
(`generated_at=2026-08-17T17:28:40+00:00`). Source:
`scripts/_tech_lab_stress_v3.py`. 9/9 checks true.

Object A (22-name drop-odd, 40 periods): competitive change 0.111721 vs
level 0.069188. Full-book change jackknife min 0.091235 (CTSH out).
software_cloud novelty jackknife min 0.088877 (CRM out); 7/7 folds beat
level.

Object B (22-name drop-odd, 40 periods): confidence level 0.054965 vs
change -0.001062. Full-book jackknife min 0.021074 (NVDA out). Semis
jackknife min 0.030250 (NVDA out).

Negative control: software confidence jackknife min -0.028109 (ADSK out),
`all_positive=false`. Not a live object in that sleeve.

Not a promotion. Same book, no holdout.
