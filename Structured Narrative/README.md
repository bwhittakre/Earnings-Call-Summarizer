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
- `quant_z` in the feature panel = PIT `dim_*_z` (not full-sample z)
- Forward alpha columns (`alpha_spec_*`) are **label-only** — excluded from default modeling export

Disable PIT guardrails (not recommended for production): `--no-pit`

## Primary deliverables

| Artifact | Path |
|----------|------|
| Interactive report | `output/{TICKER}/reports/feature_panel_report.html` |
| Research CSV | `output/{TICKER}/csv/feature_panel.csv` |
| Quarter registry | `output/{TICKER}/json/quarter_registry.json` |
| Cross-company modeling spine | `output/cross_company/csv/modeling_spine.csv` |
| **Consolidated comparison report** | `output/cross_company/reports/consolidated_feature_panel.html` |

### Cross-company comparison report

Build an interactive HTML report to compare feature panels across tickers. Two modes:

- **Compare by quarter** — align tickers on the same fiscal period; expand **+** to see dimension-level detail
- **Browse by company** — one row per ticker; expand **+** to see the full quarter × dimension panel

```powershell
python "Structured Narrative/build_consolidated_panel_report.py" --tickers AMZN MSFT NVDA AAPL
python "Structured Narrative/build_consolidated_panel_report.py" --sector mega_cap_tech --quarter FY2025-Q4
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

## Reference keys

- `feature_panel_reference_key.txt` — column dictionary
- `dimension_reference_key.txt`, `delta_reference_key.txt`, `surprise_reference_key.txt` — layer detail

## SEC confidence pipeline

The repo-root `main.py` SEC filing confidence analyzer is a **separate** pipeline. See root `README.md`.
