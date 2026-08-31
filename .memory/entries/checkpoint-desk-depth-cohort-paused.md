---
id: checkpoint-desk-depth-cohort-paused
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: Depth cohort onboarded and paused before typed closes
tags: checkpoint,desk,claims,depth,paused,august-2026
created_at: 2026-08-31T15:40:00+00:00
updated_at: 2026-08-31T15:40:00+00:00
---
Four-name depth (MSFT, CRM, LLY, ISRG) cannot finish in a
25-minute box. No delivered / hit / missed was typed. Gold
untouched. Proposer still candidates-only.

Resume pack: `data/desk_depth_cohort_pause.json`
Preview: `python scripts/_desk_depth_preview.py`

How to type a close next session: add a catalog `nodes`
entry with excerpt + `delivery_basis` or coverage, then
rebuild that book only
(`python scripts/_desk_trees_v2_ops.py` or
`python scripts/_desk_trees_v2_hc.py`). Do not invent a
terminal. Do not write into `desk_trees_v2.json`.

Next tree to adjudicate: `isrg-davinci-x`. FY2017-Q2
novelty (after FY2017-Q1 seed, before FY2017-Q4 clock)
has 11 X systems and first clinical use in Germany. That
is a delivered *candidate*, not yet typed.

CRM `crm-20b-next-goal`: FY2018-Q2 restated candidate
(chapter three $10 to $20 billion). FY2021-Q1 is a $20B
guide, not a hit. FY2021-Q4 "over $20 billion in revenue"
is a hit *candidate*.

LLY `lly-dividend-december`: clock FY2016-Q4. No dividend
excerpt in novelty FY2016-Q3 through FY2017-Q2. First
later cite is FY2017-Q4 8% increase. Do not backdate a
December 2016 delivery.

MSFT `msft-build-analyst-briefing`: clock FY2017-Q4. No
"analyst briefing" / "BUILD Developer" excerpt in novelty
FY2017-Q3 through FY2018-Q1. Existing book node is a late
silent at FY2026-Q4 that marked slipped. Do not invent
delivered.

results_json:
- metric depth_closes_typed value 0 split depth-cohort-msft-crm-lly-isrg
- metric isrg_object_hits value 7 split novelty-after-FY2017-Q1
- metric crm_object_hits value 3 split novelty-after-FY2017-Q3
- metric lly_tight_hits value 2 split novelty-after-FY2016-Q2
- metric msft_briefing_hits_in_clock value 0 split FY2017-Q3-FY2018-Q1
