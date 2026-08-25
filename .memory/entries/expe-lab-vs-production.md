---
id: expe-lab-vs-production
type: experiment
project: earnings-call-summarizer
parent_id: plan-rank-ic-phase1
title: Pre-register Lab blend vs production_v1 (asof / 0_56)
node_label: Lab vs production
tags: experiment,rank-ic,lab,pre-registered,august-2026
status: active
open_threads: 0
success: 'true'
files: ''
created_at: '2026-08-18T14:40:00+00:00'
updated_at: '2026-08-18T14:50:00+00:00'
---
Pre-registered **before** blend Rank ICs were computed. Verdict: **pass**.

## Hypothesis
On the 17 Aug 2026 Rank IC book (`generated_at=2026-08-17T17:28:40+00:00`,
25 tickers), at least one a-priori Lab blend (integer weights, **not** fitted
to Rank IC) has a higher mean period Rank IC than `production_v1` primary
(`demand` / `quant_z_pit`) on `label=asof` `horizon=0_56`.

`quant_only` (weight `quant_z_pit=1`) is a sanity check that the Lab harness
matches the Research summarizer. It is **not** a blend win.

## Pass criterion
`lab_blend_beats_primary` on split `asof-0_56-demand-17aug-book`:
any non-`quant_only` recipe has `rank_ic_mean` strictly greater than
`demand`/`quant_z_pit` on the same `company_period` rows, using
`period_rank_ics_for_selection` + `summarize_period_rank_ics`.

## Null interpretation
No unfitted blend beats the frozen primary. Keep `production_v1`. Lab stays
an exploration sandbox, not a promotion path.

## Locked parameters (not invented)
- Artifacts: `Structured Narrative/output/cross_company` from the 17 Aug regen
- Label / horizon: `production_v1.yaml` (`asof`, `0_56`)
- Universe: all 25 tickers in that eval JSON
- Dimensions reported: the three pack dimensions (`demand`, `margins`, `guidance`)
- Blend math: existing Lab path (`expanding_standardize`, `min_periods=4`)
- Recipes (integer, a priori — **not** the fitted `composite_weights` in the eval JSON):
  - `quant_only`: quant_z_pit=1
  - `equal_call_date`: all six call-date signals = 1
  - `narrative_only`: llm_level, change_magnitude, surprise_magnitude, narrative_novelty = 1
  - `agreement_only`: agrees_with_quant=1
  - `quant_plus_agreement`: quant_z_pit=1, agrees_with_quant=1
  - `quant_plus_novelty`: quant_z_pit=1, narrative_novelty=1

## Results (source: `scripts/_lab_vs_production.py`)
On split `asof-0_56-demand-17aug-book`, `generated_at=2026-08-17T17:28:40+00:00`,
25 tickers:

| recipe | rank_ic_mean | n_periods | vs primary |
|---|---|---|---|
| production demand/quant_z_pit | 0.029677 | 40 | baseline |
| equal_call_date | 0.051220 | 36 | beat |
| narrative_only | 0.040201 | 36 | beat |
| quant_only | 0.028393 | 36 | sanity, not a win |
| quant_plus_novelty | 0.028393 | 36 | no (novelty missing) |
| quant_plus_agreement | 0.019053 | 36 | no |
| agreement_only | 0.008339 | 36 | no |

`lab_blend_beats_primary=true`. Winners: `equal_call_date`, `narrative_only`.

Not a promotion: no `company_period_holdout` rows, and Lab re-standardization
drops four early periods relative to the production summarizer.

## Follow-up (pre-registered before the same-period rerun)
Hypothesis: `equal_call_date` and/or `narrative_only` still beat `demand` /
`quant_z_pit` when that primary is scored on the **same 36 periods** the Lab
path keeps after `min_periods=4`.

Pass: on split `asof-0_56-demand-17aug-book-36overlap`, a non-`quant_only`
recipe has `rank_ic_mean` strictly greater than same-window production primary.

Null: the first pass was an artifact of 36-vs-40 period mismatch. Do not treat
the original pass as a same-window result.

## Same-window results
On split `asof-0_56-demand-17aug-book-36overlap` (36 shared periods):

| recipe | rank_ic_mean | vs same-window primary |
|---|---|---|
| production demand/quant_z_pit | 0.028393 | baseline (matches quant_only) |
| equal_call_date | 0.051220 | beat |
| narrative_only | 0.040201 | beat |
| quant_only | 0.028393 | sanity match |
| quant_plus_novelty | 0.028393 | no |
| quant_plus_agreement | 0.019053 | no |
| agreement_only | 0.008339 | no |

`lab_blend_beats_primary_36overlap=true`. The 40-vs-36 gap on the primary
(+0.029677 vs +0.028393) is the four early periods the Lab window drops.
Harness consistency: same-window production primary equals Lab `quant_only`.
