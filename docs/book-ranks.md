# Book ranks (investable-as-of)

Cross-sectional ranks for the frozen **production signal pack**, published when
a period bucket’s common **investable-as-of** date is reached (latest peer T+7 /
`model_date`). No portfolio sleeve yet.

## Signal pack

Source of truth: [`config/signal_packs/production_v1.yaml`](../config/signal_packs/production_v1.yaml)

Loaded by [`Structured Narrative/signal_pack.py`](../Structured%20Narrative/signal_pack.py)
and shared with Rank IC primary hypotheses in `evaluate_narrative_signals.py`.

| Signal | Dimension |
|--------|-----------|
| `quant_z_pit` | demand |
| `agrees_with_quant` | demand |
| `agrees_with_quant` | margins |
| `agrees_with_quant` | guidance |

Bump `pack_id` (e.g. `production_v2`) when changing the set intentionally.

## Rank modes

| Mode | When | Peer set |
|------|------|----------|
| `investable_asof` (**default**) | When bucket `investable_as_of_date` ≤ today | Names with `call_feature_available_date` ≤ as-of (+ exclusions) |
| `call_day` | Optional / provisional | Latest available panels in the bucket (legacy v1) |

If FINAL lands before as-of, the worker records `skipped_reason=awaiting_investable_asof`
and **keeps the prior good ranks table**. The research-regen idle loop rebuilds
when the as-of date arrives.

## When ranks refresh

| Event | Book ranks | Rank IC research-regen dirty |
|-------|------------|------------------------------|
| LIVE post_call | No | Yes |
| FINAL post_call | Try investable-asof (may pending) | Yes |
| Regen idle + pending as-of due | Yes | n/a |
| `research-regen` / `--force` | Yes (after evaluate) | n/a |

Universe: Roz book tickers with feature panels. Requires `min_names` (default 3)
eligible peers per hypothesis or the build skips with `skipped_reason`.

## Artifacts

Under `Structured Narrative/output/cross_company/`:

- `csv/book_ranks.csv` — human-readable columns + **Metric / Meaning** key on the right
- `parquet/book_ranks.parquet` — machine schema (dashboard / regen prefer this)
- `reports/book_ranks.html` — filterable table with metric key sidebar
- `json/book_ranks_summary.json` — includes `as_of_date`, `rank_mode`, `pending`

## Manual run

```powershell
python "Structured Narrative/build_book_ranks.py" `
  --tickers MSFT AAPL NVDA MU `
  --mode investable_asof `
  --trigger-ticker MSFT `
  --trigger-period FY2026-Q2

# Provisional (ignore as-of gate):
python "Structured Narrative/build_book_ranks.py" --tickers ... --mode call_day
# Or force as-of ranks before the date:
python "Structured Narrative/build_book_ranks.py" --tickers ... --force-asof
```

## Dashboard

Roz → **Book ranks**: embeds the HTML report when present (filters + metric key).
Falls back to an interactive Streamlit table with the same key panel.

## Failure cards

| Symptom | Likely cause |
|---------|----------------|
| `skipped_reason=awaiting_investable_asof` | Bucket T+7 as-of still in the future; prior table preserved |
| `book_ranks_asof_overdue` alert | As-of passed + grace but ranks still pending |
| `skipped_reason=below_min_names` / `book_ranks_thin_peers` | Fewer than 3 eligible peers in the bucket |
| `book_ranks_failed` | FINAL subprocess error (see Operations / meta) |
| `skipped_reason=no_panels` | Missing `feature_panel.csv` for book tickers |
| LIVE scored but ranks stale | Expected — wait for FINAL + as-of |
| Dashboard empty | Artifacts not under history-source `cross_company/` mount |

## Phase 2b (not yet)

Optional equal-weight top/bottom sleeve on the same pack.
