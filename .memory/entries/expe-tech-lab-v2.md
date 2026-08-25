---
id: expe-tech-lab-v2
type: experiment
project: earnings-call-summarizer
parent_id: plan-tech-lab-v2
title: Pre-register tech Lab v2 eight-chapter case study
node_label: Tech Lab v2
tags: experiment,rank-ic,lab,tech,pre-registered,august-2026
status: active
open_threads: 0
success: 'false'
files: ''
created_at: '2026-08-18T15:50:00+00:00'
updated_at: '2026-08-18T15:50:00+00:00'
---
Pre-registered **before** v2 Rank ICs were computed. v1 results stay locked
under `expe-tech-lab-case-study` and are not re-used as confirmatory wins.

## Locked
- Artifacts: `generated_at=2026-08-17T17:28:40+00:00`, 25-ticker book
- Label / horizon: `asof` / `0_56`
- Same-window overlap as v1 (`min_periods=4` Lab path when blending)
- Single-signal comparisons use raw `company_period` (no expanding-z), because
  Rank IC of a Lab z-score is not the natural Rank IC
- No novelty weight on demand / margins / guidance / capital_allocation /
  earnings_power (signal absent)
- No `quant_guidance_revision_z_pit` (absent)
- No `surprise_magnitude` on competitive_position / macro_regulatory_risk /
  management_confidence (absent)
- Kitchen-sink `equal_call_date` / `narrative_only` excluded
- Fitted `composite_score` excluded
- `ALL_MEAN` excluded

## Chapter hold rules
A chapter **holds** only on its confirmatory primaries (ablations do not count).

1. **share_shift** — at least 2 of {C1_P_semis, C1_P_software, C1_P_designers}
   (novelty 2 + change 1 vs `llm_level` on competitive_position)
2. **cheap_talk** — at least 2 of {C2_P_all, C2_P_semis, C2_P_software}
   (natural `llm_level` > natural `change_magnitude` on management_confidence)
3. **semi_cycle** — C3_P_demand_quant_vs_surprise holds AND at least one of
   {C3_P_margins_quant_vs_level, C3_P_eps_quant_vs_level}
4. **software_duration** — C4_P_guidance_level_vs_surprise AND
   C4_P_demand_quant_vs_level
5. **investment_cycle** — at least one of {C5_P_change_vs_level,
   C5_P_surprise_vs_level} on capital_allocation / all
6. **regulatory** — at least one of {C6_P_novelty_vs_level, C6_P_change_vs_level}
   on macro_regulatory_risk / semis_cycle
7. **earnings_power** — C7_P_quant_vs_level on earnings_power / all
8. **equipment_cycle** — C8_P_demand_surprise_vs_quant on equipment / demand

## Pass criterion
`chapters_held >= 4` of 8 on split `asof-0_56-17aug-book-same-window`.

## Null interpretation
The deeper tech stories do not systematically beat their named natural
baselines on this book. Keep Lab as exploration; do not promote. The natural
atlas remains a descriptive map, not a verdict.

## Verdict
**Fail.** `chapters_held=3` of 8 on split `asof-0_56-17aug-book-same-window`
(`generated_at=2026-08-17T17:28:40+00:00`). Source:
`scripts/_tech_lab_case_study_v2.py`. 10 of 17 primaries beat their named
bar; that is not the rollup criterion.

Held: cheap_talk, investment_cycle, regulatory.
Missed: share_shift, semi_cycle, software_duration, earnings_power,
equipment_cycle.

Load-bearing reads (same split):
- Share-shift replicated in software only (C1_P_software lab 0.086664 vs
  level -0.043741, 36 periods). Semis 0.022513 vs 0.092850; designers
  0.012154 vs 0.119983.
- Cheap talk: confidence level beats change on all (0.051146 vs -0.003169),
  semis (0.080954 vs -0.024278), software (-0.005793 vs -0.078904), 40
  periods.
- Semi demand quant lost to surprise (0.023333 vs 0.043054). Semi margins
  and EPS quant beat level.
- Software demand quant lost to level (-0.099606 vs 0.025614).
- Best full-book natural cell (atlas, descriptive): competitive_position /
  change_magnitude +0.109, 40 periods, k=25.

Not a promotion. Mega/equipment k=4 cells are descriptive only.
