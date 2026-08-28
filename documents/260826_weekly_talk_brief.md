# Roz weekly — 26 August 2026

Coverage: 19 August talk through this morning. Tomorrow is the room.
Book for every Rank IC sentence: `asof`,
`generated_at=2026-08-17T17:28:40+00:00`. Not a promotion. No holdout.

## Through-line (~12 minutes)

Last week you could defend four sentences on the 17 August book.
This week you add one operational sentence: the machine will invert
a delta if the dimension view is newest-first. We caught it on UNH.
Healthcare is a **print**, not a Rank IC.

## 1. The sentence that wows (term structure)

The full-sample software-novelty U-shape is an **average of two
different curves** (`expe-term-structure-v1`):

- Early (2016-Q2..2021-Q1): +0.183 / −0.030 / +0.112
- Late (2021-Q2..2026-Q1): +0.070 / +0.083 / +0.029

`0_56` is a compound return, not the average of those buckets.
Late `0_56` +0.135418 is larger than every late bucket. Early
`0_56` +0.117970 is smaller than early `0_14`.

Typical-quarter test failed (`expe-term-structure-v3`): only **4/20**
late periods have `0_56` above the best bucket (2022-Q3, 2022-Q4,
2025-Q1, 2026-Q1). Bucket returns are nearly uncorrelated (pairwise
Spearman 0.052381). Novelty vs the z-sum of the three bucket returns
is +0.158035 — above `0_56`. The mean premium is noise cancellation
in the average, not a path most quarters take.

## 2. Do not say

- “Novelty is U-shaped” without naming the era
- “0_56 is the average of the three buckets”
- Healthcare Rank IC, or “all twenty names onboarded”
- Promotion, holdout, AI-era. The 2021-Q2 cut is the midpoint of
  40 ordered periods

## 3. Healthcare — honest status

- 13 names already have feature panels (not mixed into `xlk_tech`)
- UNH identity: Bloomberg ISIN `US91324P1021` → estpermid
  `30064860782`, Barra `USAO6Z1`, IBES **UNIH**. Do not bind UNHC
- Two-quarter UNH test (prior FY2025-Q4, output FY2026-Q1 / Q2) ran
- First UNH delta was inverted because the first-write view was
  newest-first. Pairing is now chronological. Panel has both
  FY2026-Q1 and FY2026-Q2 (16 rows) after the rescore
- LLY overlay still has Lloyds `GB0005163141`. Cleared hop was
  `US5324571083`
- Still need sourced ISINs: DHR, SYK, GILD, VRTX, ELV
- No `healthcare_large_cap` book stamp. No Rank IC on this sector

## 4. Suggested order

1. Instrumentation one-liner (PIT, asof, ISIN-first)
2. Research vs Lab vs production (frozen `production_v1`)
3. Term-structure wow + typical-quarter fail
4. UNH identity / inverted-delta catch
5. Healthcare leftovers — what is still open
