---
id: expe-tech-lab-v4
type: experiment
project: earnings-call-summarizer
parent_id: plan-tech-lab-v2
title: Pre-register time split of the two live Rank IC objects
node_label: Tech Lab v4
tags: experiment,rank-ic,lab,tech,time-split,pre-registered,august-2026
status: active
open_threads: 0
success: 'true'
files: ''
created_at: '2026-08-18T17:05:00+00:00'
updated_at: '2026-08-18T17:05:00+00:00'
---
Pre-registered **before** half-window Rank ICs were computed. v3 jackknife
results stay locked and are not re-used as new wins.

## Locked split
40 `asof` / `0_56` periods from `generated_at=2026-08-17T17:28:40+00:00`,
ordered by `calendar_quarter_sort_key` (the Rank IC Research default for
`period_end_calendar_quarter`). First 20 / last 20. Not a fitted calendar
theme — the cut is the midpoint of that ordered list.

**early** (20): 2016-Q2 … 2021-Q1
`2016-Q2, 2016-Q3, 2016-Q4, 2017-Q1, 2017-Q2, 2017-Q3, 2017-Q4, 2018-Q1,
2018-Q2, 2018-Q3, 2018-Q4, 2019-Q1, 2019-Q2, 2019-Q3, 2019-Q4, 2020-Q1,
2020-Q2, 2020-Q3, 2020-Q4, 2021-Q1`

**late** (20): 2021-Q2 … 2026-Q1
`2021-Q2, 2021-Q3, 2021-Q4, 2022-Q1, 2022-Q2, 2022-Q3, 2022-Q4, 2023-Q1,
2023-Q2, 2023-Q3, 2023-Q4, 2024-Q1, 2024-Q2, 2024-Q3, 2024-Q4, 2025-Q1,
2025-Q2, 2025-Q3, 2025-Q4, 2026-Q1`

- Natural single-signal Rank IC (raw `company_period`, no Lab z)
- Object A names: 22-name core (book minus OPAL/SPCX/STRW) for competitive
  change; `software_cloud` for novelty
- Object B names: 22-name core for confidence level; `semis_cycle` for the
  semis level check
- Same summarizer as v3

## Object A holds if all of (each half)
1. competitive `change_magnitude` > 0 on the 22-name core
2. that IC > competitive `llm_level` on the same names / same half
3. software_cloud competitive `narrative_novelty` > 0
4. that IC > software_cloud competitive `llm_level` on the same names / same half

## Object B holds if all of (each half)
1. management_confidence `llm_level` > 0 on the 22-name core
2. that IC > `change_magnitude` on the same names / same half
3. semis_cycle management_confidence `llm_level` > 0

Software confidence is a negative control and does not count.

## Pass criterion
Both objects hold on split `asof-0_56-17aug-book-early-late`.

## Null interpretation
At least one live object is an era artifact. Do not treat the 40-period
reading as persistent. Do not promote.

## Verdict
**Pass.** Both objects held on split `asof-0_56-17aug-book-early-late`
(`generated_at=2026-08-17T17:28:40+00:00`). Source:
`scripts/_tech_lab_time_split_v4.py`. 14/14 checks true.

Early (2016-Q2..2021-Q1, 20 periods, 22-name core unless noted):
- competitive change 0.119457 vs level 0.057691
- software novelty 0.117970 vs level 0.081272
- confidence level 0.088152 vs change 0.013231
- semis confidence 0.048055

Late (2021-Q2..2026-Q1, 20 periods):
- competitive change 0.103985 vs level 0.080684
- software novelty 0.135418 vs level -0.098642
- confidence level 0.021778 vs change -0.015356
- semis confidence 0.113852

Negative control (not in the bar): software confidence 0.078074 early,
-0.089659 late. The 40-period “not a software object” reading is a
late-window fact.

Not a promotion. Same book, no holdout.
