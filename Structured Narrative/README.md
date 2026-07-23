# Structured Narrative Pipeline

Evidence-backed earnings-call narrative features joined to a point-in-time (PIT) quantitative spine.

## Quick start

```powershell
# Full AMZN five-year historical run (transcripts in Structured Narrative/AMZN/)
python "Structured Narrative/run_company_pipeline.py" --ticker AMZN --scope five_year

# Incremental: score one new quarter only (uses quarter registry)
python "Structured Narrative/run_company_pipeline.py" --ticker AMZN --new-quarter FY2024-Q4

# Rebuild feature panel after quant refresh (no LLM)
python "Structured Narrative/narrative_zscore.py" --ticker AMZN
python "Structured Narrative/refresh_quant_anchors.py" --ticker AMZN
python "Structured Narrative/build_feature_panel.py" --ticker AMZN --scope five_year
```

## Point-in-time guarantee

For output quarter **FY2020-Q1**, all published quant comparisons use **expanding z-scores** computed from quarters **strictly before** FY2020-Q1 (`MIN_HISTORY=8` prior events required).

- Pre-call consensus: `effectivedate < earnings_date` (Snowflake extract)
- LLM scorers: transcript + PIT consensus block only (post-7d revisions omitted in PIT mode)
- `quant_z_pit` in the feature panel = expanding PIT `dim_*_z` for surprise-family dims (demand, margins, earnings_power, capital_allocation)
- `quant_guidance_revision_z_pit` = T+7d forward estimate revision z (delayed; separate from call-date features)
- Guidance has **no** call-date `quant_z_pit` — revisions are kept separate per methodology
- Feature availability is **feature-level**: `call_feature_available_date` (level/delta/surprise/novelty/`quant_z_pit`) and `t7_feature_available_date` (guidance revision only). Row `feature_availability_date` equals the call date for display/compat.
- Forward alpha labels are **research-only** and come in two families, each computed across
  several forward-return horizons (see "Signal IC evaluation" below for the full window table):
  - **Event-driven** `alpha_spec_{horizon}*` — from each company's T+7 / `model_date`
  - **Cross-sectional** `alpha_spec_asof_{horizon}*` — from the common `investable_as_of_date` in the calendar-quarter bucket
  Export via `export_modeling_spine.py --include-labels --labels event|asof|both [--horizons 0_14 0_56 ...]`. Do not pair T+7 revision z with a return window that starts before `t7_feature_available_date`.
  As-of/event labels need cached daily returns (`output/{TICKER}/parquet/specific_returns.parquet`), written automatically by `single_company_extractor.py` when Snowflake is reachable; new horizons beyond the legacy `0_90` window are always computed offline from that cache.
- Investable cross-section: within each `period_end_calendar_quarter`, `investable_as_of_date` = T+7 after the latest earnings date in the bucket, plus `days_since_earnings` / `feature_age_days` / `investable_ready`. Compare mode buckets by nearest calendar quarter-end (Mar/Jun/Sep/Dec), so late-month fiscal ends (e.g. NVDA Oct 31 → Sep bucket) sit with concurrent peers. Use `--min-calendar-quarter 2021-Q3` on the consolidated / spine / IC scripts to drop AMZN-only pre-history and keep a shared ~5-year four-name window.
- Pilot defaults include **AMZN, MSFT, NVDA, AAPL**. Coverage / exclusion reasons are written to `{stem}_coverage.json` when consolidating.

## Feature taxonomy

| Layer | Column(s) | Definition |
|-------|-----------|------------|
| Focus 1 — Level | `llm_level` | Absolute narrative tone this quarter (no expectations) |
| Focus 2 — Delta | `change_magnitude` | Quarter-over-quarter narrative change vs prior summary |
| Focus 3 — Surprise | `surprise_magnitude` | Narrative vs pre-call consensus (5 quant-comparable dims only) |
| Focus 3b — Novelty | `narrative_novelty` | New/material information vs prior quarter (3 narrative-only dims) |
| Quant PIT | `quant_z_pit` | Point-in-time earnings-surprise z at call date |
| Quant delayed | `quant_guidance_revision_z_pit` | T+7d forward revision z for guidance |

## Dual consolidated outputs

```powershell
# Last 8 ROIC.ai quarters per ticker + cross-section report
python "Structured Narrative/run_pilot_8q_batch.py"

# Or build the report manually after scoring (quarters = union of ROIC last-8 per ticker)
python "Structured Narrative/build_consolidated_panel_report.py" --tickers AMZN MSFT NVDA AAPL --quarters FY2025-Q1 ...

# Outputs:
#   output/cross_company/csv/cross_section_spine.csv   — slim schema for cross-sectional tests
#   output/AMZN/csv/research_spine.csv                 — full AMZN history, same slim schema
```

Slim spine columns: ticker, fiscal_period, period_end_date, period_end_calendar_quarter, earnings_date, call_feature_available_date, t7_feature_available_date, feature_availability_date, investable_as_of_date, days_since_earnings, feature_age_days, investable_ready, dimension, dimension_group, quant_mapping, level, delta, surprise, novelty, quant_z_pit, agrees_with_quant, evidence_confidence.

Consolidated panel rows use **Option B** thematic order (default `--dimension-order fundamentals_context`): fundamentals block (demand → margins → earnings_power → capital_allocation → guidance), then narrative context (management_confidence → competitive_position → macro_regulatory_risk). Other presets: `pipeline`, `behavioral`, `research_note`, `risk_first`.

Disable PIT guardrails (not recommended for production): `--no-pit`

## Primary deliverables

| Artifact | Path |
|----------|------|
| Interactive report | `output/{TICKER}/reports/feature_panel_report.html` |
| Research CSV | `output/{TICKER}/csv/feature_panel.csv` |
| Quarter registry | `output/{TICKER}/json/quarter_registry.json` |
| Cross-company modeling spine | `output/cross_company/csv/modeling_spine.csv` |
| **Consolidated comparison report** | `output/cross_company/reports/consolidated_feature_panel.html` |
| **Consolidated Excel (filterable)** | `output/cross_company/workbooks/cross_section_panel.xlsx` |

Open the **`.xlsx`** (not the CSV) in Excel for column filter dropdowns, banded rows, and structured sort on the cross-section panel.

### Cross-company comparison report

Build an interactive HTML report to compare feature panels across tickers. Two modes:

- **Compare by period-end quarter** — align tickers by **calendar quarter of fiscal period-end** (e.g. `2025-Q1` = periods ending Jan–Mar 2025), not shared fiscal labels like `FY2025-Q1`; summary table shows period ending, earnings call, and feature available dates
- **Browse by company** — one row per ticker; expand **+** to see the full quarter × dimension panel sorted by period-end date

```powershell
python "Structured Narrative/build_consolidated_panel_report.py" --tickers AMZN MSFT NVDA AAPL
python "Structured Narrative/build_consolidated_panel_report.py" --sector mega_cap_tech --quarter 2025-Q1
```

Summary JSON (including scale hooks for future lazy-load sidecars): `output/cross_company/json/consolidated_feature_panel_summary.json`

## Incremental workflow (new earnings call)

1. Drop transcript in `Structured Narrative/AMZN/FYyyyy-Qn.txt` or earnings-scraper inbox
2. Refresh quant for the new quarter (optional if spine already current):
   ```powershell
   python "Structured Narrative/run_company_pipeline.py" --ticker AMZN --skip-llm --append-quarters FY2024-Q4
   ```
3. Score the new quarter:
   ```powershell
   python "Structured Narrative/run_company_pipeline.py" --ticker AMZN --new-quarter FY2024-Q4
   ```
4. Export modeling spine:
   ```powershell
   python "Structured Narrative/export_modeling_spine.py" --tickers AMZN
   ```

Past quarters are **not re-scored** unless `--force` is passed. The registry tracks `dimensions_scored_at`, `delta_scored_at`, and `surprise_scored_at` per quarter.

## LLM cost controls — prompt caching + Batch API

Two independent, stackable cost levers on `src/llm/anthropic_client.py`, aimed at large historical
backfills (many company-quarters scored in one run) where LLM spend matters more than turnaround
speed.

**Prompt caching (always on, no flag).** Every `AnthropicClient` call — sync (`complete_json`) or
batch (`submit_batch`) — sends its `system` prompt as a cache-breakpointed block
(`cache_control: {"type": "ephemeral"}`). Each scoring stage (dimension/delta/surprise/novelty/
rescue) reuses the identical system prompt across every quarter/company, so the 2nd+ call within
the 5-minute cache TTL reads it at the discounted cache-read rate instead of paying full input
price again. The system prompt is only ~5-10% of a call's input tokens (the transcript body
dominates), so this trims a few percent of total spend — small but free; `client.usage_summary()`
reports `cache — write: …, read: …` so you can see the hit rate. `TokenUsage` carries
`cache_creation_input_tokens` / `cache_read_input_tokens` for anyone parsing audit JSON directly.

**Batch API (`--batch`, opt-in).** Anthropic's Message Batches API discounts **all** tokens
(input + output, not just the system prompt) by ~50%, at the cost of asynchronous turnaround
(Anthropic's SLA is "within 24h"; small batches — tens to low hundreds of items, the usual case
here — often finish much faster in practice, but there's no guaranteed fast tier). Pass `--batch`
to any of `run_dimension_scoring.py` / `run_delta_scoring.py` / `run_surprise_scoring.py` /
`run_novelty_scoring.py`, or to `run_company_pipeline.py` to thread it through all four:

```powershell
python "Structured Narrative/run_company_pipeline.py" --ticker AMZN --scope five_year --batch
```

Mechanics: each script fetches all pending transcripts (fast/local, unchanged), builds one
`BatchRequestItem` per quarter via the scorer's `build_request()`, submits them as a single
`AnthropicClient.submit_batch()` call, polls `get_batch()` until `processing_status == "ended"`
(`--batch-poll-interval` seconds between polls, default 30; `--batch-timeout` to cap the wait,
default none), then parses each result with `parse_batch_result()` and finishes it through the
scorer's `finalize()` — the same evidence-verification path `score()` uses. **Delta, surprise, and
novelty depend on dimensions, not on each other**: each reads the *current* (and, for delta/
novelty, *prior*) quarter's already-written dimension summary from `dimension_view.json`, so the
dimension batch must fully complete and be written to disk before their batches are built — but
delta/surprise/novelty never read each other's outputs, so nothing stops their batches from being
combined once dimensions is done (see `run_universe_batch.py` below). Any item that errors inside
a batch (a request-level failure, or a JSON that fails to parse) is retried synchronously rather
than failing the whole run — Batch API items don't get the synchronous path's automatic retry loop.

Only use `--batch` for a run where the async wait is acceptable — it's the right default for a
large backfill (e.g. the 10-year/20-company universe expansion), not for scoring one new quarter
incrementally where you want the result in seconds.

**Cross-ticker batch consolidation (`run_universe_batch.py`).** The four scripts above each batch
one ticker's items for one stage — a run across N tickers still submits up to `4 * N` separate
batches, each with its own async wait. `run_universe_batch.py` combines the *same* work into
exactly **2** batches regardless of ticker count, by exploiting the dependency graph above:

  1. **Batch group 1** — dimension-scoring items for every ticker that needs it, submitted
     together as one Message Batch.
  2. **Batch group 2** — delta + surprise + novelty items for every ticker that needs them,
     submitted **together** as one Message Batch (each item carries its own response model, since
     the three stages have different schemas; `run_batch()` accepts a `{custom_id: model}` dict for
     exactly this case).

```powershell
# Score a new quarter for all four pilot tickers in one call:
python "Structured Narrative/run_universe_batch.py" --tickers AMZN MSFT NVDA AAPL --new-quarter FY2025-Q3

# Backfill specific quarters for a subset of tickers, forcing a re-score:
python "Structured Narrative/run_universe_batch.py" --tickers MSFT NVDA AAPL --quarters FY2021-Q1 FY2021-Q2 --extra-output-quarters FY2021-Q2 --force

# Only re-run delta/surprise/novelty (skip dimensions) for two tickers:
python "Structured Narrative/run_universe_batch.py" --tickers AMZN MSFT --stages delta surprise novelty
```

This is always a batch run (there's no sync mode) — for a single ticker, or when the async wait
isn't worth it, use the four individual scripts (or `run_company_pipeline.py --batch`) instead.
Quant extraction, feature-panel building, and join/quant validation aren't LLM-batched and stay
per-ticker via `run_company_pipeline.py --skip-llm` (or run individually) after this script
finishes the LLM stages.

## Signal IC evaluation (4-name pilot)

```powershell
python "Structured Narrative/evaluate_narrative_signals.py"
python "Structured Narrative/evaluate_narrative_signals.py" --labels both --horizons 0_14 0_56
# 5-year cross-company window (matches the consolidated panel's 2021-Q3+ scope):
# omitting --quarters here means "each ticker's full registry-complete history",
# trimmed to the shared window by --min-calendar-quarter.
python "Structured Narrative/evaluate_narrative_signals.py" --min-calendar-quarter 2021-Q3
```

**Unit of observation.** Each company contributes **one** independent return observation per
cross-section. A period's eight dimension rows per company all point at the *same* forward
return, so RankIC is computed **separately for each `(period, dimension)` pair** — never pooled
across dimensions (that pooling was a bug: it inflated `n` to `4 tickers × 8 dims = 32` while
secretly repeating each company's return 8×). `by_dimension` in the JSON report / HTML holds each
dimension's own walk-forward RankIC, pooled RankIC, and quintile spread; `dimension_mean` averages
those per-dimension means for a quick cross-dimension glance — it is a display convenience, not a
statistic in its own right.

**As-of is primary; event is bucketed by earnings date.** `--labels` defaults to `asof` — the
common investable as-of construction (`period_end_calendar_quarter` grouping, `investable_ready`
rows only; `--no-investable-only` to disable) is the primary cross-sectional test. `event`
(model-date / T+7-entry, per-company) is grouped by **`earnings_date_calendar_quarter`**, not
`fiscal_period` — fiscal-period labels aren't calendar-aligned across companies (that mismatch is
the same problem `period_end_calendar_quarter` already solved for period-end dates, applied here
to the earnings date instead).

**Multiple forward horizons.** Every label is computed for several calendar-day windows from the
same T+7 entry anchor (`model_date` for event, `investable_as_of_date` for as-of), tiling
end-to-end so nothing is double-counted or skipped:

| Horizon key | Window (from T+7 entry) | Column suffix |
|---|---|---|
| `0_14`  | T+7 → T+21  | `alpha_spec[_asof]_0_14`  |
| `14_35` | T+22 → T+42 | `alpha_spec[_asof]_14_35` |
| `35_56` | T+43 → T+63 | `alpha_spec[_asof]_35_56` |
| `0_56`  | T+7 → T+63 (combined) | `alpha_spec[_asof]_0_56` |
| `0_90`  | legacy 90-day window (kept for continuity) | `alpha_spec[_asof]_0_90` |

`--horizons` restricts a run to a subset (default: all). New horizons are computed **offline**
from cached `specific_returns.parquet` — `model_date` isn't retained in `feature_panel.csv`, so
`period_dates.model_date_from(earnings_date)` recomputes it (same T+7 + weekend-roll rule used at
ingestion), and the legacy on-disk `alpha_spec_0_90*` triple is cross-checked against its own
offline recomputation as a sanity check, then left untouched either way.

**Agreement effect.** `agrees_with_quant` is categorical, so besides RankIC it gets its own
mean-return comparison: `agreement_effect_stats` reports mean forward return for agree vs.
disagree, the spread, and a **95% ticker-cluster bootstrap CI** on the spread (resampling the
ticker set, not individual rows — the same unit-of-observation fix applied to a mean comparison).
Computed per quant-mapped dimension (`demand`, `margins`, `earnings_power`, `capital_allocation`)
plus one `pooled` row, for every `(label, horizon)` combination — `--agreement-bootstrap` controls
the resample count (default 2000). With only 4 tickers the CI is wide; that reflects genuinely
limited cross-sectional power, not a bug.

**Outputs:** `output/cross_company/json/narrative_signal_eval.json` (nested `by_label[event|asof]
[horizon][signal].by_dimension[dim]`), `…_leaderboard.csv` (`signal × dimension` rows per
`label × horizon`), `…_period_ic.csv`, `…_jackknife.csv`, `…_agreement.csv`, and an interactive
HTML report at `output/cross_company/reports/narrative_signal_eval.html` with Label / Horizon /
Dimension selectors driving a period RankIC heatmap, company × quarter signal/return grid,
leaderboard, the promoted **By dimension** matrix (rows = dimension, columns = signal — the
primary "evaluate Demand/Margins/Guidance independently" view), an **Agreement effect** tab, and
jackknife.

**Dimension-aware composite signal.** `composite_score` is a 7th signal evaluated alongside the
raw ones — a walk-forward, point-in-time blend of `llm_level`, `change_magnitude`,
`surprise_magnitude`, `narrative_novelty`, `quant_z_pit`, and `agrees_with_quant`. It deliberately
excludes `evidence_confidence` (checked against the spine: constant at 1.0 across every sampled
row, so it has zero cross-sectional variance and always reports `n_dims=0` on the leaderboard — a
dead signal until the evidence-verification step gets a rubric that can produce partial scores)
and the delayed T+7 guidance-revision z (out of scope for this pass). It is fit **independently
per dimension** (never a cross-dimension rollup) and rebuilt fresh
for every `(label, horizon)` combination, since a signal's efficacy is itself horizon-dependent
(e.g. `change_magnitude` flips from +0.13 to -0.13 RankIC between the first and second 3-week
window — a composite fit against one horizon cannot reuse another's weights). See
`composite_signal.py`:

- Each input signal is **expanding-standardized** per dimension (z-scored using only rows from
  periods strictly before the row being scored, pooled across tickers) — the same PIT discipline
  `quant_z_pit` already uses, generalized to every signal so wildly different raw scales (a
  bounded LLM tone score, a boolean flag, a z-score already) become comparable before blending.
- Each input signal's **weight** at a given period is the *signed* expanding mean of its own
  walk-forward RankIC-so-far for that dimension (periods strictly before the current one). A
  consistently positive history gets a positive weight; a consistently negative one gets a
  negative weight (used contrarian, sign-flipped, rather than dropped); no history yet (warm-up,
  `--composite-min-periods`, default 4 distinct prior periods) or a wash gets ~zero weight.
- The composite is `sum(weight × standardized) / sum(|weight|)` over whatever inputs have both a
  value and a fitted weight for that row — renormalized so the scale doesn't depend on how many
  signals happen to apply to a (sparse) dimension.

Flags: `--composite` / `--no-composite` (default: on), `--composite-min-periods` (default: 4).
The JSON report's `composite_weights[{label}:{horizon}][dimension]` holds the most recent period's
fitted weight per signal, for interpretability (e.g. `asof:0_90.demand` currently reads
`{"surprise_magnitude": 0.27, "agrees_with_quant": 0.18, "llm_level": 0.17, "quant_z_pit": 0.16,
"change_magnitude": 0.07}` — not a black box).

**This is a research construct, not yet a validated model output.** With only 4 tickers and ~20
periods, the fitted weights are themselves noisy — the composite's own leaderboard RankIC is
correspondingly mixed (it beats most individual signals at some horizons, trails `agrees_with_quant`
at others), which is the expected, honest result of walk-forward-fitting on a small sample, not a
bug. The universe-expansion next step (growing the pilot beyond 4 names) would materially firm up
both the composite's weights and its own evaluated RankIC.

## Phase 1 — pre-specified hypotheses, generalized cluster bootstrap, FDR correction, dev/holdout split

Phase 1 of the Structured Narrative Expansion plan hardens the evaluation methodology itself,
ahead of (and independent from) the Phase 2/3 data expansion. All of it runs today against the
current 4-name/5-year dataset — nothing here waits on new transcripts.

**Pre-specified primary hypotheses, evaluated and corrected separately from the exploratory
grid.** `PRIMARY_HYPOTHESES` (top of `evaluate_narrative_signals.py`) hard-codes four
candidates called out ahead of time rather than picked after seeing results: demand
`quant_z_pit`, and `agrees_with_quant` for demand/margins/guidance. These get their **own**
report (`primary_hypothesis_report` in the JSON, `…_primary_hypotheses.csv`) with a per-test
p-value and a **Benjamini-Hochberg FDR correction applied once across the whole family**
(`--fdr-alpha`, default 0.05) — `q_value`/`reject_fdr` per row. The much larger exploratory
signal × dimension × horizon grid (the leaderboard) is deliberately left uncorrected, as is
standard for a screening pass; conflating the two would either under-power the exploratory scan
or under-correct the pre-specified test. Every leaderboard row also carries an `is_primary` flag
so the two families are never visually confused in the HTML/CSV output.

**Return-label timing, confirmed.** Verified (no code change needed — this was already correct):
`compound_specific_return`'s exclusive-start window means forward returns for the as-of
cross-section begin **strictly after** the common `investable_as_of_date` (itself the max T+7
date across every ticker/period in a calendar-quarter bucket — see
`period_dates.apply_investable_cross_section_columns`), and the event-aligned test begins
strictly after each company's own T+7 `model_date`. This is item 3 of the expansion plan.

**Generalized cluster bootstrap.** `cluster_bootstrap_mean_diff` replaces the
ticker-only bootstrap previously inlined in `agreement_effect_stats`, parameterized by
`cluster_col ∈ {ticker, calendar_period, company_period}` (see `_cluster_key_series`):
resampling whole clusters — not individual rows — keeps every row a cluster contributes moving
together, so a company's (or period's) repeated dimension rows are never treated as independent
observations they aren't. `agreement_effect_stats` now also returns a bootstrap `p_value` (a
two-sided test of mean_diff ≠ 0), not just a CI. A parallel period-cluster helper,
`bootstrap_rank_ic_mean`, does the equivalent for a walk-forward RankIC mean (each row of
`period_ics` is already one independent cross-section, so *periods* are the natural cluster).

**Companies-per-quarter cross-section counts.** `cross_section_counts` reports the distinct
ticker count behind every `(label, horizon)` block (`report["cross_section_counts"]`), so a
RankIC computed over `n=4` companies is never confused with one computed over `n=16` once the
universe grows — this is item 7's "number of companies in each quarterly cross-section"
requirement.

**Dev/holdout split mechanism (Phase 4 — now run against the full 10-year history).**
`--dev-cutoff YYYY-Qn` / `--holdout-start YYYY-Qn` (plus `--dev-only` / `--holdout-only`, mutually
exclusive) partition the eval frame by calendar quarter via `apply_dev_holdout_split`, before any
signal/label computation runs. Passing `--dev-cutoff` (or `--holdout-start`) **alone, with no
`--*-only` flag, is a no-op on the row count** — dev ∪ holdout is the full frame — it only tags
the `dev_holdout` metadata block; the two windows must each be evaluated with their own `--dev-only`
/ `--holdout-only` run to get independent summary statistics per window.

Because both runs otherwise write to the same fixed output filenames, `--output-tag TAG` suffixes
every artifact (`narrative_signal_eval_TAG.json`, `..._leaderboard_TAG.csv`, etc.) so a dev run and
a holdout run can coexist on disk instead of clobbering each other:

```bash
# Dev window: 2016-Q1 through 2023-Q1 (in-sample / exploratory-fit period)
python "Structured Narrative/evaluate_narrative_signals.py" --min-calendar-quarter 2016-Q1 \
  --dev-only --dev-cutoff 2023-Q1 --output-tag dev

# Holdout window: 2023-Q2 through present (genuine out-of-sample)
python "Structured Narrative/evaluate_narrative_signals.py" --min-calendar-quarter 2016-Q1 \
  --holdout-only --holdout-start 2023-Q2 --output-tag holdout
```

`--min-calendar-quarter 2016-Q1` (rather than `--quarters`) is what switches the default scope from
the small ROIC 8-quarter pilot window to each ticker's full registry-complete history — needed for
both the baseline full-history report and each dev/holdout window to actually see 10 years of data.
Composite-signal weights are refit from scratch inside whichever window is selected (each run's
walk-forward history starts over at that window's first period) — a known, transparent limitation
of filter-then-evaluate, not a bug; the raw (non-composite) signals aren't affected since they don't
carry state across periods. The report's `dev_holdout` block (including `output_tag`) records
exactly what split produced that file.

**Return units, exclusions, and feature-availability semantics** (item 7, remainder): forward
return labels (`alpha_spec*`) are **decimal specific (idiosyncratic) returns** — residualized,
compounded daily-percent specific returns from Snowflake, not raw price returns — see
"Multiple forward horizons" above for exact windows. Data exclusions: rows without a resolved
`period_end_calendar_quarter` or `investable_as_of_date` are dropped from the as-of cross-section
(no calendar bucket to join on); `--call-date-only`/default excludes any signal whose
availability date is later than the earnings call itself (see `DELAYED_SIGNALS`, currently just
`quant_guidance_revision_z_pit`) unless `--include-delayed` is passed. Feature-availability-date
semantics are documented in `feature_panel_reference_key.txt`. Universe membership rules are
documented in `universe_reference_key.txt` (Phase 0, below) once the pilot expands beyond the
current 4 names.

## Universe expansion — Phase 0: point-in-time universe reconstruction

`universe_reconstruction.py` is Phase 0 of the Structured Narrative Expansion plan: a bias-aware
candidate list for growing the pilot beyond AAPL/MSFT/NVDA/AMZN, built from SEC EDGAR filings for
the Technology Select Sector SPDR Fund (XLK) rather than read off today's holdings page — so a name
that was a constituent years ago but has since been acquired, delisted, or reclassified out of the
sector still appears in the periods it was actually a member, instead of being silently excluded by
picking today's list and projecting it backward.

```bash
python "Structured Narrative/universe_reconstruction.py"                     # full 2016-present window
python "Structured Narrative/universe_reconstruction.py" --target-n 20       # wider candidate screen
```

Outputs land in `output/universe/`: `candidate_list.csv`/`.json` (the screened net-new list),
`membership_by_filing_date.csv` (the full point-in-time audit trail), and
`historical_only_constituents.csv` (constituents that have since dropped out — kept, not discarded).
See `universe_reference_key.txt` for the full methodology: filing sources by era (N-PORT-P, N-Q,
N-CSR/N-CSRS), the CIK/series/class identifiers, known parsing gaps, and the screening rule.

## Reference keys

- `feature_panel_reference_key.txt` — column dictionary
- `dimension_reference_key.txt`, `delta_reference_key.txt`, `surprise_reference_key.txt` — layer detail
- `universe_reference_key.txt` — Phase 0 universe-reconstruction methodology (see above)

## SEC confidence pipeline

The repo-root `main.py` SEC filing confidence analyzer is a **separate** pipeline. See root `README.md`.
