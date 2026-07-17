#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared HTML rendering for single- and cross-company feature panel reports."""
from __future__ import annotations

import html
import json
from dataclasses import dataclass

import pandas as pd

from html_evidence import EVIDENCE_CSS, render_evidence_block
from dimension_order import dimension_group_label, sort_panel_by_dimension
from output_paths import resolve_read
from period_dates import calendar_quarter_display, format_us_date, quarter_cell_html

DIM_LABELS = {
    "demand": "Demand",
    "margins": "Margins",
    "earnings_power": "Earnings Power",
    "capital_allocation": "Capital Allocation",
    "guidance": "Guidance",
    "management_confidence": "Management Confidence",
    "competitive_position": "Competitive Position",
    "macro_regulatory_risk": "Macro / Regulatory Risk",
}

DELTA_DIR_LABELS = {
    "improved": "improved",
    "steady": "steady",
    "deteriorated": "deteriorated",
}

SURPRISE_DIR_LABELS = {
    "more_bullish_than_expected": "more bullish vs expected",
    "in_line": "in line",
    "more_bearish_than_expected": "more bearish vs expected",
}

FOCUS_DETAIL_BLOCKS = (
    ("level_rationale", "Focus 1 — Level", "level", "L", "Notes — transcript evidence"),
    ("delta_rationale", "Focus 2 — Delta", "delta", "D", "Notes — current-quarter change evidence"),
    ("surprise_rationale", "Focus 3 — Surprise vs consensus", "surprise", "S", "Notes — narrative evidence"),
    ("novelty_rationale", "Focus 3b — Narrative novelty", "surprise", "N", "Notes — novelty evidence"),
)

PANEL_TABLE_HEADERS = (
    "<tr><th>Quarter</th><th>Dimension</th><th>Level</th><th>Delta</th><th>Surprise</th>"
    "<th>Quant z</th><th>Gap</th><th>Flags</th><th></th></tr>"
)

BASE_CSS = """
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; padding: 24px; line-height: 1.45; color: #1c1c1e; background: #fff; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 18px; }
  .stats { font-size: 13px; margin-bottom: 12px; }
  .controls { position: sticky; top: 0; background: #fff; padding: 10px 0;
              border-bottom: 1px solid #e5e5e5; margin-bottom: 16px; z-index: 5; }
  .fbtn, .mbtn { font-size: 13px; padding: 6px 12px; margin: 0 6px 6px 0; border: 1px solid #ccc;
          border-radius: 6px; background: #f7f7f7; cursor: pointer; }
  .fbtn.active, .mbtn.active { background: #1c1c1e; color: #fff; border-color: #1c1c1e; }
  table { border-collapse: collapse; width: 100%; }
  table.inner-panel { margin: 8px 0; font-size: 13px; }
  tr.dim-group-header td { background: #eef2ff; color: #1e3a8a; font-weight: 700;
           font-size: 12px; letter-spacing: .02em; border-top: 2px solid #cbd5e1; padding: 6px 10px; }
  th, td { border: 1px solid #e2e2e2; padding: 8px 10px; vertical-align: top; text-align: left; }
  th { background: #f2f2f4; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
  td.dim { font-weight: 600; white-space: nowrap; }
  td.ticker { font-weight: 700; white-space: nowrap; }
  td.fp .fp-label { font-weight: 600; }
  td.fp .fp-sub { font-size: 11px; color: #666; line-height: 1.35; }
  td.date { font-size: 12px; white-space: nowrap; }
  td.num { text-align: center; font-variant-numeric: tabular-nums; font-weight: 600; width: 10%; }
  td.flags { width: 18%; font-size: 11px; }
  .flag { display: inline-block; margin: 1px 3px 1px 0; padding: 1px 6px; border-radius: 4px;
           text-transform: uppercase; letter-spacing: .03em; font-size: 10px; }
  .flag.diverge { color: #7a4a12; background: #fbf0df; border: 1px solid #eed6ab; }
  .flag.level-div { color: #1a4a8a; background: #e8f0fe; border: 1px solid #c5d8f5; }
  .flag.delta-div { color: #1a5c2e; background: #e6f4ea; border: 1px solid #b7dfc3; }
  .flag.surprise-div { color: #7a4a12; background: #fbf0df; border: 1px solid #eed6ab; }
  .flag.missing { color: #555; background: #f0f0f0; border: 1px solid #ddd; }
  .flag.stack { color: #334; background: #eef2f7; border: 1px solid #ccd6e0; text-transform: none; }
  .toggle { font-size: 14px; width: 28px; height: 28px; border: 1px solid #ccc; border-radius: 4px;
            background: #f7f7f7; cursor: pointer; }
  .details { padding: 8px 4px; }
  .detail { margin-bottom: 10px; }
  .detail p { margin: 4px 0 0; color: #333; }
  tr.detail-row td { background: #fafafa; }
  tr.company-row { background: #f8f9fb; }
  tr.company-row td.ticker { font-size: 14px; }
  .legend { font-size: 11px; color: #777; margin-top: 8px; }
  .mode-section { display: none; }
  .mode-section.active { display: block; }
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def mag_tint(v, hi: float = 2.0) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    frac = min(1.0, abs(f) / hi) if hi else 0.0
    alpha = round(0.12 + 0.33 * frac, 3)
    rgb = "40,150,80" if f > 0 else ("200,60,60" if f < 0 else "130,130,130")
    return f"background-color: rgba({rgb},{alpha});"


def fmt_score(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "&mdash;"
    return f"{float(v):+.1f}"


def fmt_z(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "&mdash;"
    return f"{float(v):+.2f}"


def fmt_mean(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "&mdash;"
    return f"{float(v):+.2f}"


@dataclass
class EvidenceLookups:
    level: dict[tuple[str, str], list[dict]]
    delta: dict[tuple[str, str], list[dict]]
    surprise: dict[tuple[str, str], list[dict]]


def _load_json_view(ticker: str, stem: str) -> dict | None:
    path = resolve_read(ticker, stem, "json", layer="json")
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_evidence_lookups(ticker: str) -> EvidenceLookups:
    level_map: dict[tuple[str, str], list[dict]] = {}
    dim_view = _load_json_view(ticker, "dimension_view")
    if dim_view:
        for q in dim_view.get("quarters", []):
            fp = q["fiscal_period"]
            for d in q.get("dimensions", []):
                ev = d.get("evidence") or []
                if ev:
                    level_map[(fp, d["dimension"])] = ev

    delta_map: dict[tuple[str, str], list[dict]] = {}
    delta_view = _load_json_view(ticker, "delta_view")
    if delta_view:
        for t in delta_view.get("transitions", []):
            fp = t["fiscal_period"]
            for d in t.get("deltas", []):
                ev = d.get("evidence") or []
                if ev:
                    delta_map[(fp, d["dimension"])] = ev

    surprise_map: dict[tuple[str, str], list[dict]] = {}
    surprise_view = _load_json_view(ticker, "surprise_view")
    if surprise_view:
        for q in surprise_view.get("quarters", []):
            fp = q["fiscal_period"]
            for d in q.get("surprises", []):
                ev = d.get("evidence") or []
                if ev:
                    surprise_map[(fp, d["dimension"])] = ev

    return EvidenceLookups(level=level_map, delta=delta_map, surprise=surprise_map)


def render_dimension_row(
    row: pd.Series,
    row_id: str,
    lookups: EvidenceLookups,
    *,
    show_quarter: bool = True,
) -> str:
    dim = row["dimension"]
    label = DIM_LABELS.get(dim, dim.replace("_", " ").title())
    flags = []
    if row.get("level_diverges") is True:
        flags.append('<span class="flag level-div">level diverges</span>')
    if row.get("delta_diverges") is True:
        flags.append('<span class="flag delta-div">delta diverges</span>')
    if row.get("surprise_diverges") is True or row.get("is_divergence") is True:
        flags.append('<span class="flag surprise-div">surprise diverges</span>')
    if not row.get("has_delta"):
        flags.append('<span class="flag missing">no delta</span>')
    stack = row.get("signal_stack") or ""
    if stack and isinstance(stack, str):
        flags.append(
            f'<span class="flag stack" title="{esc(stack)}">'
            f'{esc(stack[:48])}{"…" if len(stack) > 48 else ""}</span>'
        )

    cd = row.get("change_direction")
    delta_txt = "&mdash;"
    if pd.notna(row.get("change_magnitude")):
        delta_txt = f"{DELTA_DIR_LABELS.get(cd, cd or '')} {fmt_score(row.get('change_magnitude'))}"

    sd = row.get("surprise_direction")
    surpr_txt = "&mdash;"
    if pd.notna(row.get("surprise_magnitude")):
        surpr_txt = f"{SURPRISE_DIR_LABELS.get(sd, sd or '')} {fmt_score(row.get('surprise_magnitude'))}"

    nd = row.get("novelty_direction")
    novelty_txt = "&mdash;"
    if pd.notna(row.get("narrative_novelty")):
        novelty_txt = f"{nd or 'novelty'} {fmt_score(row.get('narrative_novelty'))}"

    qz = row.get("quant_z_pit") if pd.notna(row.get("quant_z_pit")) else row.get("quant_z")
    agree = row.get("agrees_with_quant")
    agree_txt = "yes" if agree is True else ("no" if agree is False else "&mdash;")
    ev_conf = row.get("evidence_confidence")
    if ev_conf is None and pd.notna(row.get("level_evidence_supported_pct")):
        pcts = [row.get(c) for c in (
            "level_evidence_supported_pct",
            "delta_evidence_supported_pct",
            "surprise_evidence_supported_pct",
            "novelty_evidence_supported_pct",
        ) if pd.notna(row.get(c))]
        ev_conf = min(pcts) if pcts else None

    ev_key = (row["fiscal_period"], dim)
    details = []
    for rationale_key, title, lookup_attr, suffix, notes_heading in FOCUS_DETAIL_BLOCKS:
        val = row.get(rationale_key)
        rationale_html = f"<p>{esc(val)}</p>" if isinstance(val, str) and val.strip() else ""

        ev_map = getattr(lookups, lookup_attr)
        evidence = ev_map.get(ev_key, [])
        evidence_html = ""
        if evidence:
            block = render_evidence_block(evidence, f"{row_id}-{suffix}", notes_heading)
            evidence_html = f'<div class="quarter-evidence" hidden>{block}</div>'

        if rationale_html or evidence_html:
            details.append(
                f'<div class="detail"><strong>{esc(title)}</strong>'
                f"{rationale_html}{evidence_html}</div>"
            )

    details_html = f'<div class="details">{"".join(details)}</div>' if details else ""
    meta = []
    if pd.notna(row.get("earnings_date")):
        meta.append(f"Earnings: {esc(row.get('earnings_date'))}")
    call_avail = row.get("call_feature_available_date") or row.get("feature_availability_date")
    if pd.notna(call_avail):
        meta.append(f"Call features: {esc(call_avail)}")
    if pd.notna(row.get("t7_feature_available_date")):
        meta.append(f"T+7 revision: {esc(row.get('t7_feature_available_date'))}")
    if pd.notna(row.get("investable_as_of_date")):
        meta.append(f"Investable as-of: {esc(row.get('investable_as_of_date'))}")
    if pd.notna(row.get("feature_age_days")):
        meta.append(f"Feature age: {int(row.get('feature_age_days'))}d")
    if row.get("quant_mapping"):
        meta.append(f"Quant map: {esc(str(row.get('quant_mapping')))}")
    meta_html = f'<div class="sub">{ " · ".join(meta)}</div>' if meta else ""
    fp_cell = f'<td class="fp">{quarter_cell_html(row)}</td>' if show_quarter else ""
    any_div = bool(
        row.get("level_diverges") is True
        or row.get("delta_diverges") is True
        or row.get("surprise_diverges") is True
        or row.get("is_divergence") is True
        or row.get("any_quant_divergence") is True
    )

    return f"""
    <tr class="data-row" data-q="{esc(row['fiscal_period'])}" data-div="{1 if any_div else 0}"
        data-delta-missing="{0 if row.get('has_delta') else 1}">
      {fp_cell}
      <td class="dim">{esc(label)}</td>
      <td class="num" style="{mag_tint(row.get('llm_level'))}">{fmt_score(row.get('llm_level'))}</td>
      <td class="num" style="{mag_tint(row.get('change_magnitude'))}">{delta_txt}</td>
      <td class="num" style="{mag_tint(row.get('surprise_magnitude'))}">{surpr_txt}</td>
      <td class="num" style="{mag_tint(row.get('narrative_novelty'))}">{novelty_txt}</td>
      <td class="num z" style="{mag_tint(qz, hi=1.5)}">{fmt_z(qz)}</td>
      <td class="num">{agree_txt}</td>
      <td class="num">{fmt_z(ev_conf) if ev_conf is not None else "&mdash;"}</td>
      <td class="num gap" style="{mag_tint(row.get('narrative_quant_gap'), hi=2.0)}">{fmt_z(row.get('narrative_quant_gap'))}</td>
      <td class="flags">{''.join(flags)}</td>
      <td class="expand"><button type="button" class="toggle" aria-expanded="false" data-target="{esc(row_id)}">+</button></td>
    </tr>
    <tr class="detail-row" id="{esc(row_id)}" hidden><td colspan="{11 if show_quarter else 10}">{meta_html}{details_html}</td></tr>
    """


def render_panel_table(
    panel: pd.DataFrame,
    lookups: EvidenceLookups,
    *,
    row_id_prefix: str,
    show_quarter: bool = True,
    table_class: str = "inner-panel",
    dimension_order: str | None = None,
    show_group_headers: bool = True,
) -> str:
    panel = sort_panel_by_dimension(panel, dimension_order)
    rows_html = []
    current_group: str | None = None
    block_key: tuple | None = None
    block_cols = tuple(
        c for c in ("period_end_date", "ticker", "fiscal_period") if c in panel.columns
    )
    n_cols = 12 if show_quarter else 11

    for i, (_, row) in enumerate(panel.iterrows()):
        if show_group_headers and "dimension_group" in panel.columns:
            if block_cols:
                key = tuple(row.get(c) for c in block_cols)
                if key != block_key:
                    block_key = key
                    current_group = None
            grp = row.get("dimension_group")
            grp_key = None if pd.isna(grp) else str(grp)
            if grp_key and grp_key != current_group:
                label = esc(dimension_group_label(grp_key))
                rows_html.append(
                    f'<tr class="dim-group-header"><td colspan="{n_cols}">{label}</td></tr>'
                )
                current_group = grp_key

        row_id = f"{row_id_prefix}-dim-{i}"
        rows_html.append(
            render_dimension_row(row, row_id, lookups, show_quarter=show_quarter)
        )
    quarter_th = "<th>Quarter</th>" if show_quarter else ""
    headers = (
        f"<tr>{quarter_th}<th>Dimension</th><th>Level</th><th>Delta</th><th>Surprise</th>"
        f"<th>Novelty</th><th>Quant PIT</th><th>Agree</th><th>Evidence</th><th>Gap</th><th>Flags</th><th></th></tr>"
    )
    return f'<table class="{table_class}"><thead>{headers}</thead><tbody>{"".join(rows_html)}</tbody></table>'


def panel_styles() -> str:
    return BASE_CSS + EVIDENCE_CSS


def toggle_and_filter_js(*, scope_selector: str = "") -> str:
    scope = f"document.querySelector('{scope_selector}') || document" if scope_selector else "document"
    return f"""
(function () {{
  var root = {scope};
  var filter = 'ALL';
  var btns = root.querySelectorAll('.fbtn');
  var dataRows = root.querySelectorAll('tr.data-row');

  function updateEvidenceVisibility() {{
    var showEvidence = filter.indexOf('q:') === 0;
    root.querySelectorAll('.quarter-evidence').forEach(function (el) {{
      el.hidden = !showEvidence;
    }});
  }}

  function applyFilter() {{
    dataRows.forEach(function (tr) {{
      var show = true;
      if (filter.indexOf('q:') === 0) {{
        show = tr.getAttribute('data-q') === filter.slice(2);
      }} else if (filter === 'div') {{
        show = tr.getAttribute('data-div') === '1';
      }} else if (filter === 'nodelta') {{
        show = tr.getAttribute('data-delta-missing') === '1';
      }}
      tr.style.display = show ? '' : 'none';
      var next = tr.nextElementSibling;
      if (next && next.classList.contains('detail-row') && !show) {{
        next.hidden = true;
        var btn = tr.querySelector('.toggle');
        if (btn) {{ btn.textContent = '+'; btn.setAttribute('aria-expanded', 'false'); }}
      }}
    }});
    btns.forEach(function (b) {{
      b.classList.toggle('active', b.getAttribute('data-filter') === filter);
    }});
    updateEvidenceVisibility();
  }}

  btns.forEach(function (b) {{
    b.addEventListener('click', function () {{
      filter = b.getAttribute('data-filter');
      applyFilter();
    }});
  }});

  root.querySelectorAll('.toggle').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      var id = btn.getAttribute('data-target');
      var detail = document.getElementById(id);
      if (!detail) return;
      var open = detail.hidden;
      detail.hidden = !open;
      btn.textContent = open ? '−' : '+';
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }});
  }});

  applyFilter();
}})();
"""


def build_single_ticker_html(panel: pd.DataFrame, summary: dict, lookups: EvidenceLookups) -> str:
    ticker = summary.get("ticker", "")
    cov = summary.get("coverage", {})
    generated = esc(summary.get("generated_at", ""))
    periods = summary.get("fiscal_periods", [])

    buttons = ['<button class="fbtn active" data-filter="ALL">All</button>']
    for fp in periods:
        buttons.append(f'<button class="fbtn" data-filter="q:{esc(fp)}">{esc(fp)}</button>')
    buttons.append('<button class="fbtn" data-filter="div">Diverges only</button>')
    buttons.append('<button class="fbtn" data-filter="nodelta">Missing delta</button>')

    rows_html = "".join(
        render_dimension_row(row, f"row-{i}", lookups)
        for i, (_, row) in enumerate(panel.iterrows())
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(ticker)} Feature Panel</title>
<style>{panel_styles()}</style>
</head>
<body>
  <h1>{esc(ticker)} Unified Feature Panel</h1>
  <div class="sub">Focus 1 level + Focus 2 delta + Focus 3 surprise + quant spine. Generated {generated}. See feature_panel_reference_key.txt.</div>
  <div class="stats">Coverage: {cov.get('has_level', 0)} level &middot; {cov.get('has_delta', 0)} delta &middot;
    {cov.get('has_surprise', 0)} surprise &middot; {cov.get('is_divergence', 0)} diverges &middot; {summary.get('row_count', 0)} rows</div>
  <div class="controls">{''.join(buttons)}
    <div class="legend">Click + to expand rationales. Select a quarter to also show claim bullets and transcript quotes. Gap = surprise magnitude minus quant z.</div>
  </div>
  <table id="main-panel">
    <thead>{PANEL_TABLE_HEADERS}</thead>
    <tbody>{rows_html}</tbody>
  </table>
<script>{toggle_and_filter_js()}</script>
</body>
</html>
"""


def _summary_flags(sub: pd.DataFrame) -> str:
    flags = []
    if "level_diverges" in sub.columns and sub["level_diverges"].fillna(False).any():
        flags.append('<span class="flag level-div">level diverges</span>')
    if "delta_diverges" in sub.columns and sub["delta_diverges"].fillna(False).any():
        flags.append('<span class="flag delta-div">delta diverges</span>')
    if (
        ("surprise_diverges" in sub.columns and sub["surprise_diverges"].fillna(False).any())
        or sub["is_divergence"].fillna(False).any()
    ):
        flags.append('<span class="flag surprise-div">surprise diverges</span>')
    if not sub["has_delta"].fillna(False).all():
        flags.append('<span class="flag missing">no delta</span>')
    return "".join(flags)


def summarize_ticker_quarter(sub: pd.DataFrame) -> dict:
    if sub.empty:
        return {
            "level_avg": None,
            "delta_avg": None,
            "surprise_avg": None,
            "quant_z_avg": None,
            "divergence_count": 0,
            "max_gap": None,
        }
    gap_col = sub.get("abs_narrative_quant_gap", sub["narrative_quant_gap"].abs())
    return {
        "level_avg": round(float(sub["llm_level"].mean()), 2) if sub["llm_level"].notna().any() else None,
        "delta_avg": round(float(sub["change_magnitude"].mean()), 2) if sub["change_magnitude"].notna().any() else None,
        "surprise_avg": round(float(sub["surprise_magnitude"].mean()), 2) if sub["surprise_magnitude"].notna().any() else None,
        "quant_z_avg": round(float(sub["quant_z"].mean()), 2) if sub["quant_z"].notna().any() else None,
        "divergence_count": int(sub["is_divergence"].fillna(False).sum()),
        "max_gap": round(float(gap_col.max()), 2) if gap_col.notna().any() else None,
    }


def build_consolidated_html(
    stacked: pd.DataFrame,
    lookups_by_ticker: dict[str, EvidenceLookups],
    *,
    tickers: list[str],
    period_buckets: list[str],
    default_bucket: str,
    sector_label: str | None,
    generated_at: str,
    dimension_order: str | None = None,
) -> str:
    sector_txt = f" &middot; Sector preset: {esc(sector_label)}" if sector_label else ""
    ticker_txt = ", ".join(tickers)

    quarter_buttons = []
    for bucket in period_buckets:
        sel = " active" if bucket == default_bucket else ""
        label = calendar_quarter_display(bucket)
        quarter_buttons.append(
            f'<button class="fbtn qbtn{sel}" data-period-bucket="{esc(bucket)}" '
            f'title="{esc(label)}">{esc(bucket)}</button>'
        )
    quarter_buttons.append('<button class="fbtn qbtn" data-period-bucket="ALL">All buckets</button>')

    compare_rows: list[str] = []
    browse_rows: list[str] = []

    for ticker in tickers:
        tpanel = stacked[stacked["ticker"] == ticker].copy()
        tpanel = sort_panel_by_dimension(tpanel, dimension_order)
        lookups = lookups_by_ticker[ticker]
        div_count = int(tpanel["is_divergence"].fillna(False).sum())

        buckets_seen: set[str] = set()
        bucket_groups = (
            tpanel.groupby("period_end_calendar_quarter", sort=False)
            if "period_end_calendar_quarter" in tpanel.columns
            else tpanel.groupby("fiscal_period", sort=False)
        )
        for bucket, grp in bucket_groups:
            if pd.isna(bucket):
                continue
            bucket = str(bucket)
            if bucket in buckets_seen:
                continue
            buckets_seen.add(bucket)

            if "period_end_date" in grp.columns and grp["period_end_date"].notna().any():
                fp = grp.sort_values("period_end_date").iloc[-1]["fiscal_period"]
            else:
                fp = grp.iloc[0]["fiscal_period"]
            qsub = tpanel[tpanel["fiscal_period"] == fp]
            meta_row = qsub.iloc[0]
            stats = summarize_ticker_quarter(qsub)
            detail_id = f"cmp-{ticker}-{bucket.replace('-', '')}"
            inner = render_panel_table(
                qsub,
                lookups,
                row_id_prefix=detail_id,
                show_quarter=False,
                table_class="inner-panel",
                dimension_order=dimension_order,
            )
            hidden = "" if bucket == default_bucket else ' style="display:none"'
            age = meta_row.get("feature_age_days")
            age_txt = str(int(age)) if age is not None and pd.notna(age) else "&mdash;"
            any_div = bool(
                stats["divergence_count"]
                or (
                    "any_quant_divergence" in qsub.columns
                    and qsub["any_quant_divergence"].fillna(False).any()
                )
            )
            compare_rows.append(f"""
    <tr class="company-row cmp-row" data-ticker="{esc(ticker)}" data-period-bucket="{esc(bucket)}"{hidden}
        data-div="{1 if any_div else 0}">
      <td class="ticker">{esc(ticker)}</td>
      <td class="fp">{quarter_cell_html(meta_row)}</td>
      <td class="date">{format_us_date(meta_row.get('period_end_date')) or '&mdash;'}</td>
      <td class="date">{format_us_date(meta_row.get('earnings_date')) or '&mdash;'}</td>
      <td class="date">{format_us_date(meta_row.get('call_feature_available_date') or meta_row.get('feature_availability_date')) or '&mdash;'}</td>
      <td class="date">{format_us_date(meta_row.get('t7_feature_available_date')) or '&mdash;'}</td>
      <td class="date">{format_us_date(meta_row.get('investable_as_of_date')) or '&mdash;'}</td>
      <td class="num">{age_txt}</td>
      <td class="num">{fmt_mean(stats['level_avg'])}</td>
      <td class="num">{fmt_mean(stats['delta_avg'])}</td>
      <td class="num">{fmt_mean(stats['surprise_avg'])}</td>
      <td class="num">{fmt_mean(stats['quant_z_avg'])}</td>
      <td class="num">{stats['divergence_count']}</td>
      <td class="num">{fmt_z(stats['max_gap'])}</td>
      <td class="flags">{_summary_flags(qsub)}</td>
      <td class="expand"><button type="button" class="toggle" aria-expanded="false" data-target="{detail_id}-wrap">+</button></td>
    </tr>
    <tr class="detail-row" id="{detail_id}-wrap" hidden><td colspan="16">{inner}</td></tr>
            """)

        if "period_end_date" in tpanel.columns and tpanel["period_end_date"].notna().any():
            latest_row = tpanel.sort_values("period_end_date").iloc[-1]
            latest_html = quarter_cell_html(latest_row)
        else:
            periods = sorted(tpanel["fiscal_period"].unique().tolist())
            latest_html = esc(periods[-1] if periods else "")

        browse_id = f"br-{ticker}"
        inner_full = render_panel_table(
            tpanel,
            lookups,
            row_id_prefix=browse_id,
            show_quarter=True,
            table_class="inner-panel",
            dimension_order=dimension_order,
        )
        n_quarters = tpanel["fiscal_period"].nunique()
        browse_rows.append(f"""
    <tr class="company-row br-row" data-ticker="{esc(ticker)}" data-div="{1 if div_count else 0}">
      <td class="ticker">{esc(ticker)}</td>
      <td>{n_quarters}</td>
      <td class="num">{len(tpanel)}</td>
      <td class="num">{div_count}</td>
      <td class="fp">{latest_html}</td>
      <td class="expand"><button type="button" class="toggle" aria-expanded="false" data-target="{browse_id}-wrap">+</button></td>
    </tr>
    <tr class="detail-row" id="{browse_id}-wrap" hidden><td colspan="6">{inner_full}</td></tr>
        """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Consolidated Feature Panel</title>
<style>{panel_styles()}</style>
</head>
<body>
  <h1>Consolidated Feature Panel</h1>
  <div class="sub">Cross-company comparison. Generated {esc(generated_at)}.{sector_txt}<br>Tickers: {esc(ticker_txt)}</div>
  <div class="controls">
    <button class="mbtn active" data-mode="compare">Compare by period-end quarter</button>
    <button class="mbtn" data-mode="browse">Browse by company</button>
    <span id="quarter-controls">{''.join(quarter_buttons)}</span>
    <button class="fbtn" data-filter="div">Diverges only</button>
    <div class="legend">Compare aligns companies by <strong>calendar quarter of fiscal period-end</strong>, not fiscal quarter label. Click + next to a company to expand its feature panel. Gap = surprise magnitude minus quant z.</div>
  </div>

  <div id="mode-compare" class="mode-section active">
    <table id="compare-table">
      <thead>
        <tr><th>Ticker</th><th>Quarter</th><th>Period ending</th><th>Earnings call</th>
            <th>Call features</th><th>T+7 revision</th><th>Investable as-of</th><th>Feature age</th>
            <th>Level avg</th><th>Delta avg</th><th>Surprise avg</th>
            <th>Quant z avg</th><th>Divergences</th><th>Max gap</th><th>Flags</th><th></th></tr>
      </thead>
      <tbody>{"".join(compare_rows)}</tbody>
    </table>
  </div>

  <div id="mode-browse" class="mode-section">
    <table id="browse-table">
      <thead>
        <tr><th>Ticker</th><th>Quarters</th><th>Rows</th><th>Divergences</th><th>Latest quarter</th><th></th></tr>
      </thead>
      <tbody>{"".join(browse_rows)}</tbody>
    </table>
  </div>

<script>
(function () {{
  var mode = 'compare';
  var selectedBucket = {json.dumps(default_bucket)};
  var filterDivOnly = false;

  function bindToggles(scope) {{
    (scope || document).querySelectorAll('.toggle').forEach(function (btn) {{
      if (btn._bound) return;
      btn._bound = true;
      btn.addEventListener('click', function () {{
        var id = btn.getAttribute('data-target');
        var detail = document.getElementById(id);
        if (!detail) return;
        var open = detail.hidden;
        detail.hidden = !open;
        btn.textContent = open ? '−' : '+';
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      }});
    }});
  }}

  function applyCompareQuarter() {{
    document.querySelectorAll('.cmp-row').forEach(function (tr) {{
      var q = tr.getAttribute('data-period-bucket');
      var showQ = (selectedBucket === 'ALL') || (q === selectedBucket);
      var showDiv = !filterDivOnly || tr.getAttribute('data-div') === '1';
      tr.style.display = (showQ && showDiv) ? '' : 'none';
      var next = tr.nextElementSibling;
      if (next && next.classList.contains('detail-row') && (!showQ || !showDiv)) {{
        next.hidden = true;
        var btn = tr.querySelector('.toggle');
        if (btn) {{ btn.textContent = '+'; btn.setAttribute('aria-expanded', 'false'); }}
      }}
    }});
    document.querySelectorAll('.qbtn').forEach(function (b) {{
      b.classList.toggle('active', b.getAttribute('data-period-bucket') === selectedBucket);
    }});
    var showEvidence = selectedBucket !== 'ALL';
    document.querySelectorAll('.quarter-evidence').forEach(function (el) {{
      el.hidden = !showEvidence;
    }});
  }}

  function applyBrowseFilter() {{
    document.querySelectorAll('.br-row').forEach(function (tr) {{
      var show = !filterDivOnly || tr.getAttribute('data-div') === '1';
      tr.style.display = show ? '' : 'none';
      var next = tr.nextElementSibling;
      if (next && next.classList.contains('detail-row') && !show) {{
        next.hidden = true;
        var btn = tr.querySelector('.toggle');
        if (btn) {{ btn.textContent = '+'; btn.setAttribute('aria-expanded', 'false'); }}
      }}
    }});
  }}

  document.querySelectorAll('.mbtn').forEach(function (b) {{
    b.addEventListener('click', function () {{
      mode = b.getAttribute('data-mode');
      document.querySelectorAll('.mbtn').forEach(function (x) {{
        x.classList.toggle('active', x === b);
      }});
      document.getElementById('mode-compare').classList.toggle('active', mode === 'compare');
      document.getElementById('mode-browse').classList.toggle('active', mode === 'browse');
      document.getElementById('quarter-controls').style.display = mode === 'compare' ? '' : 'none';
    }});
  }});

  document.querySelectorAll('.qbtn').forEach(function (b) {{
    b.addEventListener('click', function () {{
      selectedBucket = b.getAttribute('data-period-bucket');
      applyCompareQuarter();
    }});
  }});

  document.querySelectorAll('.fbtn[data-filter="div"]').forEach(function (b) {{
    b.addEventListener('click', function () {{
      filterDivOnly = !filterDivOnly;
      b.classList.toggle('active', filterDivOnly);
      if (mode === 'compare') applyCompareQuarter();
      else applyBrowseFilter();
    }});
  }});

  bindToggles(document);
  applyCompareQuarter();
}})();
</script>
</body>
</html>
"""
