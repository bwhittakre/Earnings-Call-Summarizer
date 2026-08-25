---
id: plan-healthcare-rank-ic-studies
type: plan
project: earnings-call-summarizer
parent_id: plan-healthcare-onboard
title: Healthcare Rank IC case studies (sector-specific, after onboard)
node_label: HC Rank IC studies
tags: healthcare,rank-ic,lab,case-study,plan,august-2026
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-08-20T16:25:00+00:00'
updated_at: '2026-08-20T16:25:00+00:00'
---
User asked 20 Aug 2026 to run the same major Rank IC case studies on
Healthcare Large-Cap once all 20 names are onboarded, sector-specific,
maximizing healthcare industry drivers. Not a copy of software/semis
sleeves. Not a kitchen-sink blend.

## Gate (do not compute ICs before this)
- All 20 seeded (known Quartr gaps left missing).
- `run_onboard` feature panels exist under `Structured Narrative/output/{TICKER}`.
- Research-sector book stamped (`healthcare_large_cap`, not mixed into
  `xlk_tech` / live SQLite Roz book).
- Lock `generated_at` from that pack — do not invent a stamp.
- `production_v1` stays frozen. No holdout. No promotion.
- ISIN-first identity. LLY overlay ISIN `GB0005163141` is unverified.
- Natural single-signal Rank IC on raw `company_period` for mechanism
  questions. One recipe = one dimension.

## Same three studies, healthcare objects
1. **Healthcare Lab v1** — industry stories vs natural baseline
   (`config/signal_packs/healthcare_lab_case_study_v1.yaml`). Then
   jackknife / time-split only on live objects.
2. **Horizon anatomy** — after live objects exist: is `0_56` a print
   (`0_14`) or a late bucket (`35_56`)?
3. **Term structure** — after horizon: is the shape era-stable, typical
   of quarters, and still there at `0_90`?

Optional harness first (not a case study): Lab vs production on the
healthcare book, same-window overlap. Do not recycle `equal_call_date` /
`narrative_only` into the healthcare talk.

## Sleeves (locked)
- `pharma_biotech` (10): LLY JNJ ABBV MRK PFE AMGN GILD VRTX BMY REGN
- `medtech_tools` (7): TMO ABT DHR ISRG SYK MDT BSX
- `managed_care` (3): UNH CI ELV — diagnostic only
- `healthcare_ex_payers` (17): later “not a payer object” cuts
- `all` = the 20-name healthcare book

## v1 stories (healthcare economics)
- H1 procedure/tools demand surprise vs `quant_z_pit` (`medtech_tools`)
- H2 pharma guidance tone+surprise vs guidance level (`pharma_biotech`)
- H3 pipeline/indication share novelty+change vs competitive level
- H4 IRA/pricing residual vs standing regulatory tone
- H5 R&D/BD allocation novelty vs allocation level
- H6 conviction change vs confidence level (`all`) — same question as
  tech, not the tech answer
- H7 demand confirmation control (`all`) — does not count toward rollup
- D1 payer MLR / D2 payer membership — diagnostic, k=3, not in the bar

Rollup: at least 3 of 6 story recipes (H1–H6) beat their named natural
baseline on the same names/periods. Early/late cut = midpoint of that
book's ordered `asof` / `0_56` periods, not an IRA-era theme.

Do not run until the gate is met.
