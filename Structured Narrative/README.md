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
- Forward alpha labels are **research-only** and come in two families:
  - **Event-driven** `alpha_spec_0_90*` — from each company's T+7 / `model_date`
  - **Cross-sectional** `alpha_spec_asof_0_90*` — from the common `investable_as_of_date` in the calendar-quarter bucket
  Export via `export_modeling_spine.py --include-labels --labels event|asof|both`. Do not pair T+7 revision z with a return window that starts before `t7_feature_available_date`.
  As-of labels need cached daily returns (`output/{TICKER}/parquet/specific_returns.parquet`), written automatically by `single_company_extractor.py` when Snowflake is reachable.
- Investable cross-section: within each `period_end_calendar_quarter`, `investable_as_of_date` = T+7 after the latest earnings date in the bucket, plus `days_since_earnings` / `feature_age_days` / `investable_ready`. Compare mode still buckets by period-end calendar quarter.
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
python "Structured Narrative/evaluate_narrative_signals.py" --labels both
```

- Restacks panels, recomputes **cross-ticker** `investable_as_of_date`, rebuilds `alpha_spec_asof_0_90*` from cached returns.
- **Event** label: WF by `fiscal_period` on all call-date rows.
- **As-of** label: WF by `period_end_calendar_quarter` on `investable_ready` rows (`--no-investable-only` to disable).
- Writes `output/cross_company/json/narrative_signal_eval.json`, plus `…_leaderboard.csv`, `…_period_ic.csv`, `…_jackknife.csv`.

## Reference keys

- `feature_panel_reference_key.txt` — column dictionary
- `dimension_reference_key.txt`, `delta_reference_key.txt`, `surprise_reference_key.txt` — layer detail

## SEC confidence pipeline

The repo-root `main.py` SEC filing confidence analyzer is a **separate** pipeline. See root `README.md`.
