# Structured Narrative Model — Progress Update
**Since last presentation: Thursday, Jul 16 → today, Wednesday, Jul 22**

> Note on this deck: I couldn't locate the exact "Rough Presentation" file from last week anywhere in the workspace/transcripts to copy its precise layout, so this follows the same *spirit* (progress → why it matters → link back to the model's goal) using my best judgment on structure. Flag anything that should look different and I'll adjust.

---

## 1. Where we left off (Thu Jul 16)

- Had a working 4-name pilot (AMZN, MSFT, NVDA, AAPL): narrative dimension scores joined to a PIT quant spine, with an interactive per-company report and a first cross-company consolidated panel.
- Sent the narrative-signal evaluation framework (RankIC leaderboard + HTML report) to my superior for a first read.
- Superior's response, five concrete pieces of feedback:
  1. **Unit-of-observation bug** — RankIC sample sizes (n=32) implied 4 independent cross-sectional observations were secretly 4 companies × 8 repeated dimension rows.
  2. Use the **common investable as-of construction** as the primary cross-sectional test, not the event-date version.
  3. If keeping the event version, group it by **actual earnings-date buckets**, not fiscal-quarter labels (which aren't calendar-aligned across companies).
  4. For `agrees_with_quant`, add **mean forward return by agree/disagree, the spread, and a bootstrap CI** — it's categorical, RankIC alone undersells it.
  5. Add **multiple forward horizons** (T+7–21, T+22–42, T+43–63, T+7–63) to see if any effect is immediate, delayed, or persistent.

---

## 2. This week: implemented all five, end to end

### Fix 1 — Unit of observation
- RankIC now computed **separately per `(period, dimension)` pair**, never pooled across dimensions.
- New `by_dimension` view: Demand, Margins, Guidance, etc. each get their own walk-forward RankIC, pooled RankIC, and quintile spread — exactly the "evaluate dimensions independently" ask.
- `dimension_mean` kept only as a display convenience, clearly labeled as non-statistical.

### Fix 2 & 3 — Primary test + earnings-date bucketing
- `--labels` now defaults to **`asof`** (investable as-of) as the primary cross-sectional test.
- Event-based labels now group by `earnings_date_calendar_quarter` (new column), not `fiscal_period`.

### Fix 4 — Agreement effect
- New `agreement_effect_stats`: mean forward return for agree vs. disagree, spread, **95% ticker-cluster bootstrap CI** (resamples tickers, not rows — same unit-of-observation discipline).
- Reported per dimension + pooled, for every label × horizon combination. New "Agreement effect" tab in the HTML report.

### Fix 5 — Multi-horizon labels
- 4 new windows tiling forward from T+7 entry: `0_14` (T+7→21), `14_35` (T+22→42), `35_56` (T+43→63), `0_56` (combined T+7→63) — plus the legacy `0_90` kept for continuity.
- Computed **offline** from cached daily returns (`model_date` isn't stored on disk — recomputed on the fly, same T+7 + weekend-roll rule, cross-checked against the legacy on-disk values as a sanity check).
- New **Horizon** selector in the HTML report, alongside Label and Dimension.

### What the new views actually show (fresh numbers, just regenerated)
Dimension-mean RankIC by horizon, primary (`asof`) label, 4-name / ~5-year pilot (n≈576–608 rows):

| Signal | T+7→21 | T+22→42 | T+43→63 | T+7→63 combined |
|---|---|---|---|---|
| `change_magnitude` | **+0.135** | **−0.130** | −0.107 | −0.003 |
| `agrees_with_quant` | +0.026 | +0.028 | +0.101 | +0.050 |
| `surprise_magnitude` | +0.082 | +0.013 | +0.002 | **+0.097** |
| `composite_score` (new, see below) | **+0.115** | −0.043 | +0.057 | −0.002 |

- **`change_magnitude` flips sign** between the first three weeks and the next three — a textbook example of exactly the "immediate vs. delayed" question my superior asked about. Reads as short-lived narrative momentum that reverses, not a durable signal.
- **`agrees_with_quant` builds over the quarter** instead of decaying: ~0 in the first 3 weeks → +0.10 by week 6–9 → +0.17 at the legacy ~90-day mark. The mean-return spread tells the same story: pooled agree-minus-disagree spread goes from ~0bps (T+7–21) → +1.2bps (T+22–42) → +8.8bps (T+43–63) → +29bps (~90d), with the CI narrowing away from zero as the horizon lengthens (still wide — only 4 tickers — but a consistent direction).
- Read together: **the market doesn't seem to price narrative/quant agreement right away — it shows up as a slow drift**, while narrative *tone changes* look more like short-term overreaction.

---

## 3. Data hygiene pass (the unglamorous but necessary half)

- **NVDA quarter alignment**: NVDA's fiscal quarters were bucketing to the wrong calendar quarter; fixed with a "nearest calendar quarter-end" rule, applied consistently to both period-end and earnings dates.
- **5-year, 4-name shared window**: trimmed AMZN's (and now every ticker's) history to `2021-Q3+` so the consolidated panel and the RankIC evaluation both cover the *same* 5-year, calendar-aligned window across all 4 names — not an AMZN-only extended history skewing the picture.
- **Recovered 3 missing quarters** (NVDA FY2023-Q4, MSFT FY2024-Q2, AAPL FY2024-Q3) that were silently dropped from the consolidated report by a `prior_only` flag mismatch between the registry and `company_config.py`.
- **NVDA FY2024-Q4**: was stuck prior-only (no transcript, partial score). Got the transcript, scored it, fixed a real pipeline bug in the process (a `--force` rescore was dropping *other* quarters' dimension scores on merge) — NVDA's history is now current through FY2024-Q4 like the other 3 names.
- Net effect: the RankIC table above is now running on a clean, consistent, 4-name × ~5-year panel — not one with silent gaps or a misaligned company.

---

## 4. New this week — dimension-aware composite signal

- Built `composite_score`: a 7th signal that **blends the 6 existing narrative/quant signals into one number**, per dimension, using only information legally available at that point in time (walk-forward, expanding, no lookahead).
- How it works, in one sentence: each input signal is z-scored using only *prior* periods, then weighted by its own *signed* walk-forward RankIC-so-far (a signal with a good track record gets more say; a consistently backwards one gets flipped and used contrarian; an untested one gets ~zero weight until it has ≥4 prior periods).
- Deliberately **excludes** `evidence_confidence` (checked the data — it's constant at 1.0 across every row right now, literally zero cross-sectional signal until the evidence-verification rubric can output partial scores) and the delayed T+7 guidance-revision z (separate timing scope, next pass).
- Fit **independently per dimension** and refit **fresh per horizon** — a signal's usefulness turned out to be horizon-dependent (see `change_magnitude` above), so a single global weight set would be wrong.
- Result so far: **competitive at the immediate horizon** (+0.115 RankIC, 2nd only to raw `change_magnitude`'s +0.135) but not a free lunch further out — which is the *expected, honest* result of fitting weights on ~20 periods / 4 tickers, not a bug. Weights are fully inspectable in the JSON report, not a black box.

---

## 5. Why this matters / how it ties back to the goal

The Structured Narrative model's whole point is: **does a disciplined, evidence-backed read of the earnings call add information beyond the point-in-time quant surprise?** Everything this week was in service of being able to actually answer that, honestly:

- The unit-of-observation fix wasn't cosmetic — the old n=32 pooling could have made a mediocre signal look statistically stronger than it is. Fixing it first means every number after it is trustworthy.
- Multi-horizon + the agreement-effect result are the **first real evidence of *when* the narrative signal plays out** — that's directly useful for how a composite/strategy would actually be timed.
- The composite signal is the **first attempt at the actual deliverable**: one PIT-legal score per dimension, built only from signals that have proven themselves out-of-sample so far. It's not production-ready, but it's the shape the eventual model output will take.
- The data-hygiene fixes exist so that when we say "the signal does/doesn't work," it's because of the signal — not a misaligned quarter or a silently missing data point.

---

## 6. Next steps

- **Expand the universe** beyond 4 names — the single biggest lever on statistical power; everything above is currently n=4-tickers-limited (wide bootstrap CIs, noisy composite weights).
- Investigate the `change_magnitude` reversal further — is it a real overreaction/mean-reversion effect or an artifact of a small sample?
- Get `evidence_confidence` a rubric that can produce partial scores so it's not a dead input to the composite.
- Continue hardening the pipeline (the `--force` merge bug found this week won't be the last).
