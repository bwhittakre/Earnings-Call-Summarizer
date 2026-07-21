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

## Signal IC evaluation (4-name pilot)

```powershell
python "Structured Narrative/evaluate_narrative_signals.py"
python "Structured Narrative/evaluate_narrative_signals.py" --labels both --horizons 0_14 0_56
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

## Reference keys

- `feature_panel_reference_key.txt` — column dictionary
- `dimension_reference_key.txt`, `delta_reference_key.txt`, `surprise_reference_key.txt` — layer detail

## SEC confidence pipeline

The repo-root `main.py` SEC filing confidence analyzer is a **separate** pipeline. See root `README.md`.
