#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Consolidated cross-company RankIC HTML report."""
from __future__ import annotations

import html
import json
import math
from typing import Any

import pandas as pd

from fiscal_period_util import fiscal_period_sort_key
from html_filter_presets import load_sector_presets
from period_dates import calendar_quarter_sort_key

SIGNAL_LABELS = {
    "llm_level": "Level",
    "change_magnitude": "Delta",
    "surprise_magnitude": "Surprise",
    "narrative_novelty": "Novelty",
    "quant_z_pit": "Quant z (PIT)",
    "quant_guidance_revision_z_pit": "Guidance rev z (T+7)",
    "narrative_quant_gap": "Narrative−quant gap",
    "agrees_with_quant": "Agrees with quant",
    "evidence_confidence": "Evidence confidence",
}

LABEL_DISPLAY = {
    "event": "Event (T+7 entry, earnings-date bucketed)",
    "asof": "As-of (investable, primary)",
    "custom": "Custom label",
}

DIMENSION_LABELS = {
    "demand": "Demand",
    "margins": "Margins",
    "earnings_power": "Earnings power",
    "capital_allocation": "Capital allocation",
    "guidance": "Guidance",
    "management_confidence": "Management confidence",
    "competitive_position": "Competitive position",
    "macro_regulatory_risk": "Macro / regulatory risk",
    "ALL_MEAN": "All dimensions (mean, display-only)",
}


def esc(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _finite(x: Any) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def fmt_ic(v: Any, digits: int = 3) -> str:
    f = _finite(v)
    if f is None:
        return "—"
    return f"{f:+.{digits}f}"


def ic_cell_style(v: Any, *, hi: float = 0.6) -> str:
    f = _finite(v)
    if f is None:
        return "background:#f3f3f3;color:#999;"
    frac = min(1.0, abs(f) / hi) if hi else 0.0
    alpha = round(0.10 + 0.45 * frac, 3)
    rgb = "34,140,70" if f > 0 else ("190,50,50" if f < 0 else "140,140,140")
    return f"background:rgba({rgb},{alpha});"


def signal_cell_style(v: Any, *, hi: float = 2.0) -> str:
    f = _finite(v)
    if f is None:
        return "background:#f3f3f3;color:#999;"
    frac = min(1.0, abs(f) / hi) if hi else 0.0
    alpha = round(0.10 + 0.40 * frac, 3)
    rgb = "40,120,180" if f > 0 else ("180,90,30" if f < 0 else "140,140,140")
    return f"background:rgba({rgb},{alpha});"


def sort_periods(periods: list[str], period_col: str) -> list[str]:
    if period_col in ("period_end_calendar_quarter", "earnings_date_calendar_quarter"):
        return sorted(periods, key=lambda p: calendar_quarter_sort_key(str(p)))
    return sorted(periods, key=lambda p: fiscal_period_sort_key(str(p)))


def company_period_signal_rows(
    df: pd.DataFrame,
    signals: list[str],
    label: str,
    *,
    period_col: str,
    label_key: str,
    universe: str = "all",
    horizon: str | None = None,
) -> list[dict]:
    """Per ticker × period × signal × dimension: mean signal + mean forward label.

    Emits one row per real dimension (the corrected, unit-of-observation-safe
    view) plus a synthetic "ALL_MEAN" dimension row per (ticker, period, signal)
    that averages across dimensions — a display-only convenience for a quick
    cross-dimension glance, not a substitute for the per-dimension walk-forward
    RankIC in the "By dimension" view.
    """
    if df.empty or label not in df.columns or period_col not in df.columns:
        return []
    work = df[df[label].notna()].copy()
    if universe == "investable_ready" and "investable_ready" in work.columns:
        work = work[work["investable_ready"] == True].copy()  # noqa: E712
    has_dim = "dimension" in work.columns
    rows: list[dict] = []
    for signal in signals:
        if signal not in work.columns:
            continue
        cols = ["ticker", period_col, signal, label] + (["dimension"] if has_dim else [])
        sub = work[cols].dropna(subset=[signal, label])
        if sub.empty:
            continue

        if has_dim:
            grouped = (
                sub.groupby(["ticker", period_col, "dimension"], dropna=False)
                .agg(signal_mean=(signal, "mean"), label_mean=(label, "mean"), n=(signal, "count"))
                .reset_index()
            )
            for _, r in grouped.iterrows():
                rows.append(
                    {
                        "label_key": label_key,
                        "horizon": horizon,
                        "label": label,
                        "period_col": period_col,
                        "universe": universe,
                        "ticker": str(r["ticker"]).upper(),
                        "period": str(r[period_col]),
                        "signal": signal,
                        "dimension": str(r["dimension"]),
                        "signal_mean": _finite(r["signal_mean"]),
                        "label_mean": _finite(r["label_mean"]),
                        "n": int(r["n"]),
                    }
                )

        all_grouped = (
            sub.groupby(["ticker", period_col], dropna=False)
            .agg(signal_mean=(signal, "mean"), label_mean=(label, "mean"), n=(signal, "count"))
            .reset_index()
        )
        for _, r in all_grouped.iterrows():
            rows.append(
                {
                    "label_key": label_key,
                    "horizon": horizon,
                    "label": label,
                    "period_col": period_col,
                    "universe": universe,
                    "ticker": str(r["ticker"]).upper(),
                    "period": str(r[period_col]),
                    "signal": signal,
                    "dimension": "ALL_MEAN",
                    "signal_mean": _finite(r["signal_mean"]),
                    "label_mean": _finite(r["label_mean"]),
                    "n": int(r["n"]),
                }
            )
    return rows


def _period_ic_payload(period_frames: list[pd.DataFrame] | pd.DataFrame | None) -> list[dict]:
    if period_frames is None:
        return []
    if isinstance(period_frames, list):
        if not period_frames:
            return []
        pdf = pd.concat(period_frames, ignore_index=True)
    else:
        pdf = period_frames
    if pdf.empty:
        return []
    out = []
    for _, r in pdf.iterrows():
        dim = r.get("dimension")
        out.append(
            {
                "period": str(r.get("fiscal_period")),
                "period_col": str(r.get("period_col") or "fiscal_period"),
                "dimension": str(dim) if pd.notna(dim) else None,
                "signal": str(r.get("signal")),
                "label": str(r.get("label")),
                "label_key": str(r.get("label_key")) if pd.notna(r.get("label_key")) else "custom",
                "horizon": str(r.get("horizon")) if pd.notna(r.get("horizon")) else None,
                "n": int(r["n"]) if pd.notna(r.get("n")) else None,
                "ic": _finite(r.get("ic")),
                "rank_ic": _finite(r.get("rank_ic")),
                "universe": str(r.get("universe") or "all"),
            }
        )
    return out


CSS = """
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; padding: 24px; line-height: 1.45; color: #1c1c1e; background: #fff; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 22px 0 8px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 14px; }
  .controls { position: sticky; top: 0; background: #fff; padding: 10px 0 12px;
              border-bottom: 1px solid #e5e5e5; margin-bottom: 16px; z-index: 5; }
  .ctrl-row { margin-bottom: 4px; }
  .ctrl-row-label { display: inline-block; font-size: 10px; text-transform: uppercase;
              letter-spacing: .04em; color: #999; width: 68px; }
  .fbtn, .mbtn, .sbtn, .hbtn, .dbtn { font-size: 13px; padding: 6px 12px; margin: 0 6px 6px 0;
          border: 1px solid #ccc; border-radius: 6px; background: #f7f7f7; cursor: pointer; }
  .fbtn.active, .mbtn.active, .sbtn.active, .hbtn.active, .dbtn.active {
          background: #1c1c1e; color: #fff; border-color: #1c1c1e; }
  .legend { font-size: 11px; color: #777; margin-top: 6px; max-width: 960px; }
  .mode-section { display: none; }
  .mode-section.active { display: block; }
  table { border-collapse: collapse; width: max-content; max-width: 100%; font-size: 12px; }
  th, td { border: 1px solid #e2e2e2; padding: 6px 8px; text-align: center;
           font-variant-numeric: tabular-nums; white-space: nowrap; }
  th { background: #f2f2f4; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; }
  th.sticky-col, td.sticky-col { position: sticky; left: 0; background: #fafafa;
           text-align: left; font-weight: 700; z-index: 1; }
  th.sticky-col { z-index: 2; background: #f2f2f4; }
  td.muted { color: #999; }
  .scroll { overflow-x: auto; border: 1px solid #eee; border-radius: 6px; }
  .card { margin-bottom: 18px; }
  .meta { font-size: 12px; color: #555; margin-bottom: 8px; }
  .cell-sub { display: block; font-size: 10px; color: #555; font-weight: 500; }
  .hint { font-size: 12px; color: #666; margin: 0 0 10px; }
  .ci-wrap { display: flex; align-items: center; gap: 6px; justify-content: center; }
  .ci-track { position: relative; width: 140px; height: 14px; background: #f2f2f4;
              border-radius: 3px; }
  .ci-zero { position: absolute; top: 0; bottom: 0; left: 50%; width: 1px; background: #999; }
  .ci-band { position: absolute; top: 4px; bottom: 4px; border-radius: 2px; }
  .ci-marker { position: absolute; top: 1px; bottom: 1px; width: 2px; background: #1c1c1e; }
  .warn-box { font-size: 12px; color: #8a5a00; background: #fff8e6; border: 1px solid #f0dca0;
              border-radius: 6px; padding: 8px 10px; margin: 0 0 10px; max-width: 900px; }
  .company-filter-label { font-size: 12px; color: #555; margin: 0 6px 0 0; }
  .company-filter { font-size: 13px; padding: 6px 10px; margin: 0 6px 6px 0; border: 1px solid #ccc;
          border-radius: 6px; background: #f7f7f7; max-width: 180px; }
  .company-filter-bar { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 4px 0; }
  .company-check-wrap { display: inline-flex; flex-wrap: wrap; gap: 4px 10px;
          max-width: 720px; margin: 0 8px 6px 0; padding: 6px 8px; border: 1px solid #e5e5e5;
          border-radius: 6px; background: #fafafa; max-height: 96px; overflow-y: auto; }
  .company-check-wrap label { font-size: 12px; white-space: nowrap; cursor: pointer; }
  .cf-mini { font-size: 12px; padding: 4px 8px; margin: 0 4px 6px 0; }
  .filter-caption { font-size: 12px; color: #555; margin: 0 0 8px; }
"""


def build_rank_ic_report_html(
    report: dict,
    *,
    period_ics: list[dict] | None = None,
    company_period: list[dict] | None = None,
) -> str:
    """Build interactive RankIC HTML from evaluate_narrative_signals report payload."""
    tickers = [str(t).upper() for t in (report.get("tickers") or [])]
    generated = report.get("generated_at") or ""
    leaderboard = report.get("leaderboard") or []
    jackknife = report.get("jackknife") or []
    agreement = report.get("agreement_effect") or []
    by_label = report.get("by_label") or {}
    horizon_windows = report.get("horizon_windows") or {}

    label_keys = list(by_label.keys()) or sorted(
        {r.get("label") for r in leaderboard if r.get("label")}
    )
    if not label_keys:
        label_keys = ["event"]

    horizon_keys = list(report.get("horizons") or [])
    if not horizon_keys:
        seen: list[str] = []
        for lk in label_keys:
            for hk in (by_label.get(lk) or {}).keys():
                if hk not in seen:
                    seen.append(hk)
        horizon_keys = seen or ["0_90"]

    signals: list[str] = []
    for lk in label_keys:
        for hk in horizon_keys:
            for s in ((by_label.get(lk) or {}).get(hk) or {}).keys():
                if s not in signals:
                    signals.append(s)
    if not signals:
        signals = sorted({r["signal"] for r in leaderboard if r.get("signal")})

    dimensions: list[str] = []
    for r in leaderboard:
        d = r.get("dimension")
        if d and d != "ALL_MEAN" and d not in dimensions:
            dimensions.append(d)
    dimensions = sorted(dimensions) + (["ALL_MEAN"] if any(r.get("dimension") == "ALL_MEAN" for r in leaderboard) else [])

    period_payload = period_ics if period_ics is not None else []
    company_payload = company_period or []

    # Period lists per label_key (unioned across horizons for that label family).
    periods_by_label: dict[str, list[str]] = {}
    period_col_by_label: dict[str, str] = {}
    for row in period_payload:
        lk = row.get("label_key") or "custom"
        periods_by_label.setdefault(lk, [])
        p = str(row.get("period"))
        if p and p not in periods_by_label[lk]:
            periods_by_label[lk].append(p)
        period_col_by_label[lk] = str(row.get("period_col") or "fiscal_period")
    for lk, plist in list(periods_by_label.items()):
        periods_by_label[lk] = sort_periods(plist, period_col_by_label.get(lk, "fiscal_period"))

    default_label = "asof" if "asof" in label_keys else label_keys[0]
    primary_horizon = report.get("primary_horizon")
    default_horizon = (
        primary_horizon
        if primary_horizon in horizon_keys
        else ("0_56" if "0_56" in horizon_keys else horizon_keys[0])
    )
    default_dimension = "ALL_MEAN" if "ALL_MEAN" in dimensions else (dimensions[0] if dimensions else "ALL_MEAN")
    default_signal = next(
        (
            r["signal"]
            for r in leaderboard
            if r.get("label") == default_label
            and r.get("horizon") == default_horizon
            and _finite(r.get("rank_ic_mean")) is not None
        ),
        signals[0] if signals else "llm_level",
    )

    # Dimension × signal matrix (the promoted "By dimension" view) plus
    # dimension_mean, straight from the report's by_label tree.
    dimension_matrix: dict[str, dict[str, dict[str, dict]]] = {}
    for lk, horizons in by_label.items():
        dimension_matrix[lk] = {}
        for hk, signals_block in horizons.items():
            dimension_matrix[lk][hk] = {}
            for sig, stats in signals_block.items():
                dimension_matrix[lk][hk][sig] = {
                    "by_dimension": stats.get("by_dimension") or {},
                    "dimension_mean": stats.get("dimension_mean") or {},
                }

    payload = {
        "tickers": tickers,
        "signals": signals,
        "signal_labels": SIGNAL_LABELS,
        "label_keys": label_keys,
        "label_display": {k: LABEL_DISPLAY.get(k, k) for k in label_keys},
        "horizon_keys": horizon_keys,
        "horizon_display": {k: horizon_windows.get(k, k) for k in horizon_keys},
        "dimensions": dimensions,
        "dimension_labels": DIMENSION_LABELS,
        "default_label": default_label,
        "default_horizon": default_horizon,
        "default_dimension": default_dimension,
        "default_signal": default_signal,
        "periods_by_label": periods_by_label,
        "period_col_by_label": period_col_by_label,
        "leaderboard": leaderboard,
        "period_ics": period_payload,
        "company_period": company_payload,
        "jackknife": jackknife,
        "agreement_effect": agreement,
        "dimension_matrix": dimension_matrix,
        "meta": {
            "generated_at": generated,
            "n_rows": report.get("n_rows"),
            "n_rows_by_label": report.get("n_rows_by_label"),
            "investable_only_for_asof": report.get("investable_only_for_asof"),
            "label_overlap": report.get("label_overlap"),
            "primary_label_key": report.get("primary_label_key"),
            "primary_horizon": report.get("primary_horizon"),
        },
    }

    label_buttons = "".join(
        f'<button class="fbtn lbtn{" active" if lk == default_label else ""}" data-label="{esc(lk)}">'
        f'{esc(LABEL_DISPLAY.get(lk, lk))}</button>'
        for lk in label_keys
    )
    horizon_buttons = "".join(
        f'<button class="hbtn{" active" if hk == default_horizon else ""}" data-horizon="{esc(hk)}">'
        f'{esc(horizon_windows.get(hk, hk))}</button>'
        for hk in horizon_keys
    )
    dimension_buttons = "".join(
        f'<button class="dbtn{" active" if d == default_dimension else ""}" data-dimension="{esc(d)}">'
        f'{esc(DIMENSION_LABELS.get(d, d))}</button>'
        for d in dimensions
    )
    signal_buttons = "".join(
        f'<button class="sbtn{" active" if s == default_signal else ""}" data-signal="{esc(s)}">'
        f'{esc(SIGNAL_LABELS.get(s, s))}</button>'
        for s in signals
    )

    sector_presets = load_sector_presets(tickers)
    preset_options = ['<option value="" data-preset="">All companies</option>']
    for stem in sector_presets:
        preset_options.append(
            f'<option value="{esc(stem)}" data-preset="{esc(stem)}">{esc(stem)}</option>'
        )
    checklist_html = "".join(
        f'<label><input type="checkbox" class="company-check" value="{esc(t)}" checked> {esc(t)}</label>'
        for t in tickers
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cross-Company RankIC</title>
<style>{CSS}</style>
</head>
<body>
  <h1>Cross-Company RankIC</h1>
  <div class="sub">
    Walk-forward Spearman RankIC across {esc(", ".join(tickers) or "tickers")}.
    Generated {esc(generated)}.
  </div>

  <div class="controls">
    <div class="ctrl-row">
      <span class="ctrl-row-label">View</span>
      <button class="mbtn active" data-mode="heatmap">Period RankIC heatmap</button>
      <button class="mbtn" data-mode="company">Company × quarter</button>
      <button class="mbtn" data-mode="leaderboard">Leaderboard</button>
      <button class="mbtn" data-mode="dimension">By dimension</button>
      <button class="mbtn" data-mode="agreement">Agreement effect</button>
      <button class="mbtn" data-mode="jackknife">Jackknife</button>
    </div>
    <div class="ctrl-row">
      <span class="ctrl-row-label">Label</span>
      <span id="label-controls">{label_buttons}</span>
    </div>
    <div class="ctrl-row">
      <span class="ctrl-row-label">Horizon</span>
      <span id="horizon-controls">{horizon_buttons}</span>
    </div>
    <div class="ctrl-row" id="dimension-controls-row">
      <span class="ctrl-row-label">Dimension</span>
      <span id="dimension-controls">{dimension_buttons}</span>
    </div>
    <div class="ctrl-row" id="signal-controls-row">
      <span class="ctrl-row-label">Signal</span>
      <span id="signal-controls">{signal_buttons}</span>
    </div>
    <div class="ctrl-row" id="company-filter">
      <span class="ctrl-row-label">Universe</span>
      <div class="company-filter-bar">
        <label class="company-filter-label" for="sector-preset">Sector</label>
        <select id="sector-preset" class="company-filter" title="Sector preset">{''.join(preset_options)}</select>
        <button type="button" class="fbtn cf-mini" id="cf-all">All</button>
        <button type="button" class="fbtn cf-mini" id="cf-none">None</button>
        <div class="company-check-wrap" id="company-checks">{checklist_html}</div>
      </div>
    </div>
    <div class="legend">
      <strong>Unit of observation:</strong> RankIC is computed separately for each
      (period, dimension) cross-section — a company contributes at most one point per
      dimension per period, never one point per (company × 8 dimensions) sharing the
      same forward return. Pick a real dimension to see that cross-section directly, or
      use <strong>By dimension</strong> for the full Demand/Margins/Guidance/… breakdown.
      <strong>ALL_MEAN</strong> (Company × quarter / Leaderboard only) averages the
      per-dimension results for a quick glance — it is not itself a statistic.
      <strong>As-of</strong> is the primary cross-sectional test (investable-ready rows,
      grouped by period-end calendar quarter). <strong>Event</strong>, when shown, is
      grouped by the earnings date's calendar quarter (fiscal-period labels aren't
      calendar-aligned across companies). Horizons are calendar-day windows from each
      name's own T+7 entry date. Cells: green / blue = higher; red / orange = lower.
      Sector / company filters recompute period Rank IC client-side from embedded
      company×period data (honor <code>?tickers=</code> / <code>?preset=</code> from Roz).
    </div>
  </div>

  <div id="mode-heatmap" class="mode-section active">
    <div class="meta" id="heatmap-meta"></div>
    <div class="filter-caption" id="filter-caption"></div>
    <p class="hint">Rows = signals, columns = periods, for the selected dimension. Cell = RankIC
       for that period's (dimension-scoped) cross-section.</p>
    <div id="heatmap-warn"></div>
    <div class="scroll card" id="heatmap-wrap"></div>
  </div>

  <div id="mode-company" class="mode-section">
    <div class="meta" id="company-meta"></div>
    <p class="hint">Rows = companies, columns = periods for the selected signal / dimension.
       Top line = mean signal; bottom line = mean forward label (specific return).</p>
    <div class="scroll card" id="company-wrap"></div>
  </div>

  <div id="mode-leaderboard" class="mode-section">
    <div class="meta" id="leaderboard-meta"></div>
    <div class="scroll card" id="leaderboard-wrap"></div>
  </div>

  <div id="mode-dimension" class="mode-section">
    <div class="meta" id="dimension-meta"></div>
    <p class="hint">Rows = narrative dimension, columns = signal. Cell = walk-forward RankIC mean
       (hover for pooled RankIC / n). This is the corrected, per-dimension unit of observation —
       evaluate Demand, Margins, Guidance, … independently instead of pooling them.</p>
    <div class="scroll card" id="dimension-wrap"></div>
  </div>

  <div id="mode-agreement" class="mode-section">
    <div class="meta" id="agreement-meta"></div>
    <p class="hint">Mean forward return when the narrative agrees vs. disagrees with the quant
       surprise, by dimension (plus a ticker-cluster-bootstrapped "pooled" row across the
       quant-mapped dimensions). CI is a 95% ticker-cluster bootstrap on the spread — wide with
       only a handful of companies, which reflects real cross-sectional power, not a bug.</p>
    <div class="scroll card" id="agreement-wrap"></div>
  </div>

  <div id="mode-jackknife" class="mode-section">
    <div class="meta" id="jackknife-meta"></div>
    <p class="hint">Leave-one-ticker-out RankIC mean for the selected signal / label / horizon /
       dimension. Small samples: dropping a ticker from an already ≤4-point cross-section can
       leave some periods below the minimum n=3 — expect sparser coverage here than elsewhere.</p>
    <div id="jackknife-warn"></div>
    <div class="scroll card" id="jackknife-wrap"></div>
  </div>

<script>
const DATA = {json.dumps(payload, allow_nan=False)};
const SECTOR_PRESETS = {json.dumps(sector_presets, allow_nan=False)};
/* RANK_IC_CLIENT_RECOMPUTE */

(function () {{
  let mode = 'heatmap';
  let labelKey = DATA.default_label;
  let horizonKey = DATA.default_horizon;
  let dimensionKey = DATA.default_dimension;
  let signal = DATA.default_signal;

  function fmt(v, d) {{
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    const n = Number(v);
    const sign = n > 0 ? '+' : '';
    return sign + n.toFixed(d === undefined ? 3 : d);
  }}

  function pct(v, d) {{
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    return (Number(v) * 100).toFixed(d === undefined ? 2 : d) + '%';
  }}

  function icStyle(v) {{
    if (v === null || v === undefined || Number.isNaN(v)) return 'background:#f3f3f3;color:#999;';
    const hi = 0.6;
    const frac = Math.min(1, Math.abs(v) / hi);
    const alpha = (0.10 + 0.45 * frac).toFixed(3);
    const rgb = v > 0 ? '34,140,70' : (v < 0 ? '190,50,50' : '140,140,140');
    return 'background:rgba(' + rgb + ',' + alpha + ');';
  }}

  function sigStyle(v) {{
    if (v === null || v === undefined || Number.isNaN(v)) return 'background:#f3f3f3;color:#999;';
    const hi = 2.0;
    const frac = Math.min(1, Math.abs(v) / hi);
    const alpha = (0.10 + 0.40 * frac).toFixed(3);
    const rgb = v > 0 ? '40,120,180' : (v < 0 ? '180,90,30' : '140,140,140');
    return 'background:rgba(' + rgb + ',' + alpha + ');';
  }}

  function signalName(s) {{
    return (DATA.signal_labels && DATA.signal_labels[s]) || s;
  }}

  function labelName(k) {{
    return (DATA.label_display && DATA.label_display[k]) || k;
  }}

  function horizonName(k) {{
    return (DATA.horizon_display && DATA.horizon_display[k]) || k;
  }}

  function dimensionName(d) {{
    return (DATA.dimension_labels && DATA.dimension_labels[d]) || d;
  }}

  function setActive(selector, attr, value) {{
    document.querySelectorAll(selector).forEach(function (btn) {{
      btn.classList.toggle('active', btn.getAttribute(attr) === value);
    }});
  }}

  function selectedTickers() {{
    const out = [];
    document.querySelectorAll('.company-check').forEach(function (cb) {{
      if (cb.checked) out.push(cb.value);
    }});
    return out;
  }}

  function setChecks(tickers) {{
    const want = {{}};
    (tickers || []).forEach(function (t) {{ want[String(t).toUpperCase()] = true; }});
    document.querySelectorAll('.company-check').forEach(function (cb) {{
      cb.checked = !!want[cb.value];
    }});
  }}

  function setAllChecks(on) {{
    document.querySelectorAll('.company-check').forEach(function (cb) {{ cb.checked = !!on; }});
  }}

  function isFullUniverse(sel) {{
    const all = DATA.tickers || [];
    if (!all.length) return true;
    if (!sel || sel.length !== all.length) return false;
    const set = {{}};
    sel.forEach(function (t) {{ set[t] = true; }});
    for (let i = 0; i < all.length; i++) {{
      if (!set[all[i]]) return false;
    }}
    return true;
  }}

  function updateFilterCaption() {{
    const el = document.getElementById('filter-caption');
    if (!el) return;
    const sel = selectedTickers();
    if (isFullUniverse(sel)) {{
      el.textContent = '';
      return;
    }}
    el.textContent = 'Rank IC recomputed for ' + sel.length + ' companies.';
  }}

  // RANK_IC_CLIENT_RECOMPUTE — average-rank Spearman (parity with spearman_ic.py).
  function spearmanRankIC(xs, ys) {{
    const pairs = [];
    const nIn = Math.min(xs.length, ys.length);
    for (let i = 0; i < nIn; i++) {{
      const x = xs[i], y = ys[i];
      if (x === null || x === undefined || y === null || y === undefined) continue;
      if (Number.isNaN(x) || Number.isNaN(y)) continue;
      pairs.push([Number(x), Number(y)]);
    }}
    const n = pairs.length;
    if (n < 3) return null;
    const xv = pairs.map(function (p) {{ return p[0]; }});
    const yv = pairs.map(function (p) {{ return p[1]; }});
    function ranks(vals) {{
      const order = vals.map(function (_, i) {{ return i; }})
        .sort(function (a, b) {{ return vals[a] - vals[b]; }});
      const out = new Array(n);
      let i = 0;
      while (i < n) {{
        let j = i;
        while (j + 1 < n && vals[order[j + 1]] === vals[order[i]]) j++;
        const avg = (i + j) / 2.0 + 1.0;
        for (let k = i; k <= j; k++) out[order[k]] = avg;
        i = j + 1;
      }}
      return out;
    }}
    const rx = ranks(xv);
    const ry = ranks(yv);
    let meanX = 0, meanY = 0;
    for (let i = 0; i < n; i++) {{ meanX += rx[i]; meanY += ry[i]; }}
    meanX /= n; meanY /= n;
    let num = 0, denX = 0, denY = 0;
    for (let i = 0; i < n; i++) {{
      const dx = rx[i] - meanX, dy = ry[i] - meanY;
      num += dx * dy;
      denX += dx * dx;
      denY += dy * dy;
    }}
    denX = Math.sqrt(denX); denY = Math.sqrt(denY);
    if (denX === 0 || denY === 0) return null;
    return num / (denX * denY);
  }}

  function recomputePeriodICs(sel) {{
    const want = {{}};
    sel.forEach(function (t) {{ want[t] = true; }});
    const periods = DATA.periods_by_label[labelKey] || [];
    const out = [];
    DATA.signals.forEach(function (sig) {{
      periods.forEach(function (period) {{
        const xs = [], ys = [];
        (DATA.company_period || []).forEach(function (r) {{
          if (r.label_key !== labelKey || r.horizon !== horizonKey) return;
          if (r.signal !== sig || r.dimension !== dimensionKey) return;
          if (r.period !== period || !want[r.ticker]) return;
          if (r.signal_mean === null || r.signal_mean === undefined) return;
          if (r.label_mean === null || r.label_mean === undefined) return;
          if (Number.isNaN(r.signal_mean) || Number.isNaN(r.label_mean)) return;
          xs.push(r.signal_mean);
          ys.push(r.label_mean);
        }});
        const ric = spearmanRankIC(xs, ys);
        if (ric === null) return;
        out.push({{
          label_key: labelKey,
          horizon: horizonKey,
          dimension: dimensionKey,
          signal: sig,
          period: period,
          n: xs.length,
          rank_ic: ric,
          ic: null
        }});
      }});
    }});
    return out;
  }}

  function summarizePeriodICs(periodRows, sig) {{
    const vals = periodRows.filter(function (r) {{ return r.signal === sig; }})
      .map(function (r) {{ return r.rank_ic; }})
      .filter(function (v) {{ return v !== null && v !== undefined && !Number.isNaN(v); }});
    if (!vals.length) {{
      return {{ rank_ic_mean: null, rank_ic_ir: null, positive_rank_ic_hit_rate: null, n_periods: 0 }};
    }}
    const mean = vals.reduce(function (a, b) {{ return a + b; }}, 0) / vals.length;
    let variance = 0;
    vals.forEach(function (v) {{ variance += (v - mean) * (v - mean); }});
    const std = Math.sqrt(variance / vals.length);
    const ir = std > 0 ? mean / std : null;
    const hit = vals.filter(function (v) {{ return v > 0; }}).length / vals.length;
    return {{
      rank_ic_mean: mean,
      rank_ic_ir: ir,
      positive_rank_ic_hit_rate: hit,
      n_periods: vals.length
    }};
  }}

  function activePeriodICs() {{
    const sel = selectedTickers();
    if (isFullUniverse(sel)) {{
      return DATA.period_ics.filter(function (r) {{
        return r.label_key === labelKey && r.horizon === horizonKey && r.dimension === dimensionKey;
      }});
    }}
    return recomputePeriodICs(sel);
  }}

  function ciBarHtml(spread, lo, hi, maxAbs) {{
    if (maxAbs === undefined || !maxAbs) maxAbs = 0.05;
    const scale = function (v) {{
      const clamped = Math.max(-maxAbs, Math.min(maxAbs, v));
      return 50 + (clamped / maxAbs) * 48;
    }};
    let band = '';
    if (lo !== null && lo !== undefined && hi !== null && hi !== undefined &&
        !Number.isNaN(lo) && !Number.isNaN(hi)) {{
      const left = Math.min(scale(lo), scale(hi));
      const right = Math.max(scale(lo), scale(hi));
      const crossesZero = lo < 0 && hi > 0;
      const color = crossesZero ? '160,160,160' : (spread >= 0 ? '34,140,70' : '190,50,50');
      band = '<span class="ci-band" style="left:' + left.toFixed(1) + '%;width:' +
        Math.max(1, right - left).toFixed(1) + '%;background:rgba(' + color + ',0.35);"></span>';
    }}
    let marker = '';
    if (spread !== null && spread !== undefined && !Number.isNaN(spread)) {{
      marker = '<span class="ci-marker" style="left:' + scale(spread).toFixed(1) + '%;"></span>';
    }}
    return '<div class="ci-track">' + band + '<span class="ci-zero"></span>' + marker + '</div>';
  }}

  function showMode() {{
    document.querySelectorAll('.mode-section').forEach(function (el) {{
      el.classList.toggle('active', el.id === 'mode-' + mode);
    }});
    setActive('.mbtn', 'data-mode', mode);
    const needSignal = mode === 'company' || mode === 'jackknife';
    const needDimension = mode === 'heatmap' || mode === 'company' || mode === 'leaderboard' || mode === 'jackknife';
    document.getElementById('signal-controls-row').style.display = needSignal ? '' : 'none';
    document.getElementById('dimension-controls-row').style.display = needDimension ? '' : 'none';
    render();
  }}

  function noAllMeanWarning(target) {{
    if (dimensionKey !== 'ALL_MEAN') return false;
    document.getElementById(target).innerHTML =
      '<div class="warn-box">ALL_MEAN has no per-period cross-section by design — pooling every ' +
      'dimension into one cross-section is exactly the unit-of-observation bug that was fixed. ' +
      'Pick a real dimension above, or use the <strong>By dimension</strong> tab for the full ' +
      'breakdown.</div>';
    return true;
  }}

  function renderHeatmap() {{
    document.getElementById('heatmap-warn').innerHTML = '';
    updateFilterCaption();
    if (noAllMeanWarning('heatmap-wrap')) {{
      document.getElementById('heatmap-meta').textContent = '';
      return;
    }}
    const periods = DATA.periods_by_label[labelKey] || [];
    const rows = activePeriodICs();
    const byKey = {{}};
    rows.forEach(function (r) {{ byKey[r.signal + '||' + r.period] = r; }});
    let htmlStr = '<table><thead><tr><th class="sticky-col">Signal</th>';
    periods.forEach(function (p) {{ htmlStr += '<th>' + p + '</th>'; }});
    htmlStr += '<th>Mean</th></tr></thead><tbody>';
    DATA.signals.forEach(function (sig) {{
      htmlStr += '<tr><td class="sticky-col">' + signalName(sig) + '</td>';
      const vals = [];
      periods.forEach(function (p) {{
        const cell = byKey[sig + '||' + p];
        const v = cell ? cell.rank_ic : null;
        if (v !== null && v !== undefined) vals.push(v);
        const title = cell
          ? ('n=' + cell.n + '  RankIC=' + fmt(cell.rank_ic) + '  IC=' + fmt(cell.ic))
          : 'n/a';
        htmlStr += '<td style="' + icStyle(v) + '" title="' + title + '">' + fmt(v) + '</td>';
      }});
      const mean = vals.length ? vals.reduce(function (a,b){{return a+b;}},0) / vals.length : null;
      htmlStr += '<td style="' + icStyle(mean) + '"><strong>' + fmt(mean) + '</strong></td></tr>';
    }});
    htmlStr += '</tbody></table>';
    document.getElementById('heatmap-wrap').innerHTML = htmlStr;
    document.getElementById('heatmap-meta').textContent =
      labelName(labelKey) + ' · ' + horizonName(horizonKey) + ' · ' + dimensionName(dimensionKey) +
      ' · periods bucketed by ' + ((DATA.period_col_by_label && DATA.period_col_by_label[labelKey]) || 'fiscal_period');
  }}

  function renderCompany() {{
    updateFilterCaption();
    const periods = DATA.periods_by_label[labelKey] || [];
    const sel = selectedTickers();
    const want = {{}};
    sel.forEach(function (t) {{ want[t] = true; }});
    const rows = DATA.company_period.filter(function (r) {{
      return r.label_key === labelKey && r.horizon === horizonKey &&
        r.signal === signal && r.dimension === dimensionKey && want[r.ticker];
    }});
    const byKey = {{}};
    rows.forEach(function (r) {{ byKey[r.ticker + '||' + r.period] = r; }});
    const tickers = sel.length ? sel : (DATA.tickers || []);
    let htmlStr = '<table><thead><tr><th class="sticky-col">Ticker</th>';
    periods.forEach(function (p) {{ htmlStr += '<th>' + p + '</th>'; }});
    htmlStr += '</tr></thead><tbody>';
    tickers.forEach(function (t) {{
      htmlStr += '<tr><td class="sticky-col">' + t + '</td>';
      periods.forEach(function (p) {{
        const cell = byKey[t + '||' + p];
        if (!cell) {{
          htmlStr += '<td class="muted">—</td>';
          return;
        }}
        const title = 'signal=' + fmt(cell.signal_mean) + '  label=' + fmt(cell.label_mean, 5) + '  n=' + cell.n;
        htmlStr += '<td style="' + sigStyle(cell.signal_mean) + '" title="' + title + '">' +
          fmt(cell.signal_mean, 2) +
          '<span class="cell-sub">r ' + fmt(cell.label_mean, 4) + '</span></td>';
      }});
      htmlStr += '</tr>';
    }});
    if (dimensionKey !== 'ALL_MEAN') {{
      const pic = activePeriodICs().filter(function (r) {{ return r.signal === signal; }});
      const picMap = {{}};
      pic.forEach(function (r) {{ picMap[r.period] = r; }});
      htmlStr += '<tr><td class="sticky-col">Period RankIC</td>';
      periods.forEach(function (p) {{
        const cell = picMap[p];
        const v = cell ? cell.rank_ic : null;
        htmlStr += '<td style="' + icStyle(v) + '"><strong>' + fmt(v) + '</strong></td>';
      }});
      htmlStr += '</tr>';
    }}
    htmlStr += '</tbody></table>';
    document.getElementById('company-wrap').innerHTML = htmlStr;
    document.getElementById('company-meta').textContent =
      signalName(signal) + ' · ' + labelName(labelKey) + ' · ' + horizonName(horizonKey) +
      ' · ' + dimensionName(dimensionKey);
  }}

  function renderLeaderboard() {{
    updateFilterCaption();
    const sel = selectedTickers();
    let rows;
    if (isFullUniverse(sel)) {{
      rows = DATA.leaderboard.filter(function (r) {{
        return r.label === labelKey && r.horizon === horizonKey && r.dimension === dimensionKey;
      }});
    }} else {{
      const periodRows = recomputePeriodICs(sel);
      rows = DATA.signals.map(function (sig) {{
        const stats = summarizePeriodICs(periodRows, sig);
        return {{
          signal: sig,
          label: labelKey,
          horizon: horizonKey,
          dimension: dimensionKey,
          rank_ic_mean: stats.rank_ic_mean,
          rank_ic_ir: stats.rank_ic_ir,
          pooled_rank_ic: null,
          positive_rank_ic_hit_rate: stats.positive_rank_ic_hit_rate,
          n_periods: stats.n_periods,
          n_rows: null,
          universe: 'subset:' + sel.length
        }};
      }});
    }}
    rows = rows.slice().sort(function (a, b) {{
      const av = (a.rank_ic_mean === null || a.rank_ic_mean === undefined) ? -999 : a.rank_ic_mean;
      const bv = (b.rank_ic_mean === null || b.rank_ic_mean === undefined) ? -999 : b.rank_ic_mean;
      return bv - av;
    }});
    let htmlStr = '<table><thead><tr>' +
      '<th class="sticky-col">Signal</th><th>RankIC mean</th><th>IR</th><th>Pooled RankIC</th>' +
      '<th>Hit rate</th><th>Periods</th><th>Rows</th><th>Universe</th></tr></thead><tbody>';
    if (!rows.length) {{
      htmlStr += '<tr><td colspan="8" class="muted">No leaderboard rows for this selection.</td></tr>';
    }}
    rows.forEach(function (r) {{
      htmlStr += '<tr><td class="sticky-col">' + signalName(r.signal) + '</td>' +
        '<td style="' + icStyle(r.rank_ic_mean) + '">' + fmt(r.rank_ic_mean) + '</td>' +
        '<td>' + fmt(r.rank_ic_ir) + '</td>' +
        '<td style="' + icStyle(r.pooled_rank_ic) + '">' + fmt(r.pooled_rank_ic) + '</td>' +
        '<td>' + fmt(r.positive_rank_ic_hit_rate, 2) + '</td>' +
        '<td>' + (r.n_periods || '—') + '</td>' +
        '<td>' + (r.n_rows || '—') + '</td>' +
        '<td>' + (r.universe || '—') + '</td></tr>';
    }});
    htmlStr += '</tbody></table>';
    document.getElementById('leaderboard-wrap').innerHTML = htmlStr;
    document.getElementById('leaderboard-meta').textContent =
      labelName(labelKey) + ' · ' + horizonName(horizonKey) + ' · ' + dimensionName(dimensionKey);
  }}

  function renderDimension() {{
    const block = ((DATA.dimension_matrix[labelKey] || {{}})[horizonKey]) || {{}};
    const dims = (DATA.dimensions || []).filter(function (d) {{ return d !== 'ALL_MEAN'; }});
    let htmlStr = '<table><thead><tr><th class="sticky-col">Dimension</th>';
    DATA.signals.forEach(function (sig) {{ htmlStr += '<th>' + signalName(sig) + '</th>'; }});
    htmlStr += '</tr></thead><tbody>';
    dims.forEach(function (dim) {{
      htmlStr += '<tr><td class="sticky-col">' + dimensionName(dim) + '</td>';
      DATA.signals.forEach(function (sig) {{
        const stats = (block[sig] || {{}}).by_dimension || {{}};
        const dstat = stats[dim];
        const wf = (dstat || {{}}).walk_forward || {{}};
        const v = wf.rank_ic_mean;
        const title = dstat
          ? ('n_periods=' + (wf.n_periods || 0) + '  pooled=' + fmt(dstat.pooled_rank_ic) +
             '  n_rows=' + (dstat.n_rows || 0))
          : 'n/a';
        htmlStr += '<td style="' + icStyle(v) + '" title="' + title + '">' + fmt(v) + '</td>';
      }});
      htmlStr += '</tr>';
    }});
    htmlStr += '<tr><td class="sticky-col"><strong>All dims (mean)</strong></td>';
    DATA.signals.forEach(function (sig) {{
      const dm = ((block[sig] || {{}}).dimension_mean) || {{}};
      htmlStr += '<td style="' + icStyle(dm.rank_ic_mean) + '"><strong>' + fmt(dm.rank_ic_mean) + '</strong></td>';
    }});
    htmlStr += '</tr></tbody></table>';
    document.getElementById('dimension-wrap').innerHTML = htmlStr;
    document.getElementById('dimension-meta').textContent =
      labelName(labelKey) + ' · ' + horizonName(horizonKey);
  }}

  function renderAgreement() {{
    const rows = DATA.agreement_effect.filter(function (r) {{
      return r.label_key === labelKey && r.horizon === horizonKey;
    }});
    let maxAbs = 0.01;
    rows.forEach(function (r) {{
      [r.spread, r.ci_low, r.ci_high].forEach(function (v) {{
        if (v !== null && v !== undefined && !Number.isNaN(v)) maxAbs = Math.max(maxAbs, Math.abs(v));
      }});
    }});
    let htmlStr = '<table><thead><tr><th class="sticky-col">Dimension</th>' +
      '<th>n agree</th><th>n disagree</th><th>Mean return (agree)</th>' +
      '<th>Mean return (disagree)</th><th>Spread</th><th>95% CI (ticker bootstrap)</th>' +
      '<th># tickers</th></tr></thead><tbody>';
    if (!rows.length) {{
      htmlStr += '<tr><td colspan="8" class="muted">No agreement-effect rows for this selection.</td></tr>';
    }}
    rows.forEach(function (r) {{
      const dimLabel = r.dimension === 'pooled' ? 'All quant dims (pooled)' : dimensionName(r.dimension);
      htmlStr += '<tr><td class="sticky-col">' + dimLabel + '</td>' +
        '<td>' + (r.n_agree || 0) + '</td>' +
        '<td>' + (r.n_disagree || 0) + '</td>' +
        '<td>' + pct(r.mean_return_agree) + '</td>' +
        '<td>' + pct(r.mean_return_disagree) + '</td>' +
        '<td style="' + icStyle(r.spread ? r.spread / maxAbs * 0.6 : null) + '">' + pct(r.spread) + '</td>' +
        '<td><div class="ci-wrap">' + ciBarHtml(r.spread, r.ci_low, r.ci_high, maxAbs) +
        '<span>[' + pct(r.ci_low) + ', ' + pct(r.ci_high) + ']</span></div></td>' +
        '<td>' + (r.n_tickers || 0) + '</td></tr>';
    }});
    htmlStr += '</tbody></table>';
    document.getElementById('agreement-wrap').innerHTML = htmlStr;
    document.getElementById('agreement-meta').textContent =
      labelName(labelKey) + ' · ' + horizonName(horizonKey) +
      ' · agrees_with_quant vs. forward specific return';
  }}

  function renderJackknife() {{
    document.getElementById('jackknife-warn').innerHTML = '';
    updateFilterCaption();
    if (noAllMeanWarning('jackknife-wrap')) {{
      document.getElementById('jackknife-meta').textContent = '';
      return;
    }}
    const sel = selectedTickers();
    const want = {{}};
    sel.forEach(function (t) {{ want[t] = true; }});
    const rows = DATA.jackknife.filter(function (r) {{
      return r.signal === signal && r.label_key === labelKey && r.horizon === horizonKey &&
        r.dimension === dimensionKey && want[r.held_out_ticker];
    }});
    let htmlStr = '';
    if (!isFullUniverse(sel)) {{
      htmlStr += '<div class="warn-box">Jackknife leave-one-out matrix is full-book; showing held-out rows for selected tickers only (values not recomputed for the subset).</div>';
    }}
    htmlStr += '<table><thead><tr><th class="sticky-col">Held out</th>' +
      '<th>RankIC mean</th><th>IR</th><th>Pooled RankIC</th><th>Periods</th><th>Rows</th></tr></thead><tbody>';
    if (!rows.length) {{
      htmlStr += '<tr><td colspan="6" class="muted">No jackknife rows for this selection.</td></tr>';
    }} else {{
      rows.forEach(function (r) {{
        htmlStr += '<tr><td class="sticky-col">' + r.held_out_ticker + '</td>' +
          '<td style="' + icStyle(r.rank_ic_mean) + '">' + fmt(r.rank_ic_mean) + '</td>' +
          '<td>' + fmt(r.rank_ic_ir) + '</td>' +
          '<td style="' + icStyle(r.pooled_rank_ic) + '">' + fmt(r.pooled_rank_ic) + '</td>' +
          '<td>' + (r.n_periods || '—') + '</td>' +
          '<td>' + (r.n_rows || '—') + '</td></tr>';
      }});
    }}
    htmlStr += '</tbody></table>';
    document.getElementById('jackknife-wrap').innerHTML = htmlStr;
    document.getElementById('jackknife-meta').textContent =
      signalName(signal) + ' · ' + labelName(labelKey) + ' · ' + horizonName(horizonKey) +
      ' · ' + dimensionName(dimensionKey);
  }}

  function render() {{
    if (mode === 'heatmap') renderHeatmap();
    else if (mode === 'company') renderCompany();
    else if (mode === 'leaderboard') renderLeaderboard();
    else if (mode === 'dimension') renderDimension();
    else if (mode === 'agreement') renderAgreement();
    else if (mode === 'jackknife') renderJackknife();
  }}

  function initUrlFilters() {{
    try {{
      const params = new URLSearchParams(window.location.search);
      const preset = params.get('preset');
      const raw = params.get('tickers');
      const sel = document.getElementById('sector-preset');
      if (preset && SECTOR_PRESETS[preset]) {{
        if (sel) sel.value = preset;
        setChecks(SECTOR_PRESETS[preset]);
        return;
      }}
      if (raw) {{
        const list = raw.split(',').map(function (s) {{ return s.trim().toUpperCase(); }}).filter(Boolean);
        if (list.length) {{
          if (sel) sel.value = '';
          setChecks(list);
        }}
      }}
    }} catch (e) {{}}
  }}

  document.querySelectorAll('.mbtn').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      mode = btn.getAttribute('data-mode');
      showMode();
    }});
  }});
  document.querySelectorAll('.lbtn').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      labelKey = btn.getAttribute('data-label');
      setActive('.lbtn', 'data-label', labelKey);
      render();
    }});
  }});
  document.querySelectorAll('.hbtn').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      horizonKey = btn.getAttribute('data-horizon');
      setActive('.hbtn', 'data-horizon', horizonKey);
      render();
    }});
  }});
  document.querySelectorAll('.dbtn').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      dimensionKey = btn.getAttribute('data-dimension');
      setActive('.dbtn', 'data-dimension', dimensionKey);
      render();
    }});
  }});
  document.querySelectorAll('.sbtn').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      signal = btn.getAttribute('data-signal');
      setActive('.sbtn', 'data-signal', signal);
      render();
    }});
  }});

  const sectorSel = document.getElementById('sector-preset');
  if (sectorSel) {{
    sectorSel.addEventListener('change', function () {{
      const stem = sectorSel.value;
      if (stem && SECTOR_PRESETS[stem]) setChecks(SECTOR_PRESETS[stem]);
      else setAllChecks(true);
      render();
    }});
  }}
  const cfAll = document.getElementById('cf-all');
  if (cfAll) cfAll.addEventListener('click', function () {{
    if (sectorSel) sectorSel.value = '';
    setAllChecks(true);
    render();
  }});
  const cfNone = document.getElementById('cf-none');
  if (cfNone) cfNone.addEventListener('click', function () {{
    if (sectorSel) sectorSel.value = '';
    setAllChecks(false);
    render();
  }});
  document.querySelectorAll('.company-check').forEach(function (cb) {{
    cb.addEventListener('change', function () {{
      if (sectorSel) sectorSel.value = '';
      render();
    }});
  }});

  initUrlFilters();
  showMode();
}})();
</script>
</body>
</html>
"""
