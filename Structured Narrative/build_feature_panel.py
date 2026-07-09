#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified long-format feature panel: Focus 1 level + Focus 2 delta + Focus 3 surprise + quant spine.

    python "Structured Narrative/build_feature_panel.py"
    python "Structured Narrative/build_feature_panel.py" --ticker AMZN --full-spine
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from dimension_scorer import ALL_DIMENSIONS, QUANT_COMPARABLE_DIMENSIONS  # noqa: E402

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

PANEL_COLUMNS = [
    "ticker",
    "fiscal_period",
    "dimension",
    "as_of_date",
    "earnings_date",
    "quant_z",
    "quant_z_pit",
    "alpha_spec_0_90",
    "alpha_spec_0_90_z",
    "alpha_spec_0_90_complete",
    "llm_level",
    "level_rationale",
    "level_evidence_supported_pct",
    "prior_period",
    "change_direction",
    "change_magnitude",
    "score_delta",
    "quant_z_delta",
    "delta_rationale",
    "delta_evidence_supported_pct",
    "surprise_direction",
    "surprise_magnitude",
    "agrees_with_quant",
    "narrative_quant_gap",
    "surprise_rationale",
    "surprise_evidence_supported_pct",
    "has_level",
    "has_delta",
    "has_surprise",
    "level_quant_sign_match",
    "delta_quant_sign_match",
    "is_divergence",
    "signal_stack",
]


def _read(base: str) -> pd.DataFrame:
    p_parquet = OUT_DIR / f"{base}.parquet"
    p_csv = OUT_DIR / f"{base}.csv"
    if p_parquet.exists():
        try:
            return pd.read_parquet(p_parquet)
        except Exception:
            pass
    if p_csv.exists():
        return pd.read_csv(p_csv)
    raise FileNotFoundError(f"Missing {base}.parquet/.csv in {OUT_DIR}")


def _evidence_pct(n_verified, n_total, verified_flag) -> float | None:
    if pd.notna(n_total) and int(n_total) > 0:
        return round(float(n_verified) / float(n_total), 4)
    if verified_flag is True:
        return 1.0
    if verified_flag is False:
        return 0.0
    return None


def _same_sign(a, b) -> bool | None:
    if pd.isna(a) or pd.isna(b):
        return None
    fa, fb = float(a), float(b)
    if fa == 0 and fb == 0:
        return True
    if fa == 0 or fb == 0:
        return None
    return (fa > 0) == (fb > 0)


def _signal_stack(row: pd.Series) -> str:
    parts: list[str] = []
    ll = row.get("llm_level")
    if pd.notna(ll):
        if ll > 0.3:
            parts.append("bullish_level")
        elif ll < -0.3:
            parts.append("bearish_level")
        else:
            parts.append("neutral_level")
    cm = row.get("change_magnitude")
    if pd.notna(cm):
        if cm > 0.05:
            parts.append("delta_up")
        elif cm < -0.05:
            parts.append("delta_down")
        else:
            parts.append("delta_flat")
    sd = row.get("surprise_direction")
    if sd == "more_bullish_than_expected":
        parts.append("surprise_bullish")
    elif sd == "more_bearish_than_expected":
        parts.append("surprise_bearish")
    elif sd == "in_line":
        parts.append("surprise_inline")
    if row.get("is_divergence") is True:
        parts.append("quant_diverges")
    return "|".join(parts)


def build_spine(quant: pd.DataFrame, ticker: str) -> pd.DataFrame:
    rows: list[dict] = []
    for _, row in quant.iterrows():
        fp = row["fiscal_period"]
        meta = {
            "ticker": ticker,
            "fiscal_period": fp,
            "as_of_date": row.get("earnings_date"),
            "earnings_date": row.get("earnings_date"),
            "alpha_spec_0_90": row.get("alpha_spec_0_90"),
            "alpha_spec_0_90_z": row.get("alpha_spec_0_90_z"),
            "alpha_spec_0_90_complete": row.get("alpha_spec_0_90_complete"),
        }
        for dim in ALL_DIMENSIONS:
            rec = dict(meta)
            rec["dimension"] = dim
            if dim in QUANT_COMPARABLE_DIMENSIONS:
                rec["quant_z"] = row.get(f"dim_{dim}_z")
                rec["quant_z_pit"] = row.get(f"dim_{dim}_z_pit")
            else:
                rec["quant_z"] = None
                rec["quant_z_pit"] = None
            rows.append(rec)
    return pd.DataFrame(rows)


def build_spine_from_level(level: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Build panel spine from LLM level rows when quant dimension_scores are unavailable."""
    rows: list[dict] = []
    for _, row in level.iterrows():
        rec = {
            "ticker": ticker,
            "fiscal_period": row["fiscal_period"],
            "dimension": row["dimension"],
            "as_of_date": row.get("as_of_date"),
            "earnings_date": row.get("as_of_date"),
            "quant_z": None,
            "quant_z_pit": None,
            "alpha_spec_0_90": None,
            "alpha_spec_0_90_z": None,
            "alpha_spec_0_90_complete": None,
        }
        rows.append(rec)
    return pd.DataFrame(rows)


def _read_optional(base: str) -> pd.DataFrame | None:
    try:
        return _read(base)
    except FileNotFoundError:
        return None


def prepare_level(level: pd.DataFrame) -> pd.DataFrame:
    df = level.copy()
    df["level_evidence_supported_pct"] = df.apply(
        lambda r: _evidence_pct(r.get("n_evidence_verified"), r.get("n_evidence"), r.get("evidence_verified")),
        axis=1,
    )
    return df.rename(
        columns={
            "score": "llm_level",
            "rationale": "level_rationale",
        }
    )[
        [
            "ticker",
            "fiscal_period",
            "dimension",
            "as_of_date",
            "llm_level",
            "level_rationale",
            "level_evidence_supported_pct",
        ]
    ]


def prepare_delta(delta: pd.DataFrame) -> pd.DataFrame:
    df = delta.copy()
    df["delta_evidence_supported_pct"] = df.apply(
        lambda r: _evidence_pct(r.get("n_evidence_verified"), r.get("n_evidence"), r.get("evidence_verified")),
        axis=1,
    )
    return df.rename(columns={"rationale": "delta_rationale"})[
        [
            "ticker",
            "fiscal_period",
            "dimension",
            "as_of_date",
            "prior_period",
            "change_direction",
            "change_magnitude",
            "score_delta",
            "quant_z_delta",
            "delta_rationale",
            "delta_evidence_supported_pct",
        ]
    ]


def prepare_surprise(surprise: pd.DataFrame) -> pd.DataFrame:
    df = surprise.copy()
    df["surprise_evidence_supported_pct"] = df.apply(
        lambda r: _evidence_pct(r.get("n_evidence_verified"), r.get("n_evidence"), r.get("evidence_verified")),
        axis=1,
    )
    return df.rename(columns={"rationale": "surprise_rationale"})[
        [
            "ticker",
            "fiscal_period",
            "dimension",
            "as_of_date",
            "surprise_direction",
            "surprise_magnitude",
            "agrees_with_quant",
            "narrative_quant_gap",
            "surprise_rationale",
            "surprise_evidence_supported_pct",
        ]
    ]


def merge_panel(
    spine: pd.DataFrame,
    level: pd.DataFrame,
    delta: pd.DataFrame,
    surprise: pd.DataFrame,
    *,
    full_spine: bool,
) -> pd.DataFrame:
    keys = ["ticker", "fiscal_period", "dimension"]
    panel = spine.merge(level, on=keys, how="left", suffixes=("", "_level"))
    panel = panel.merge(delta, on=keys, how="left", suffixes=("", "_delta"))
    panel = panel.merge(surprise, on=keys, how="left", suffixes=("", "_surprise"))

    for src in ("_level", "_delta", "_surprise"):
        col = f"as_of_date{src}"
        if col in panel.columns:
            panel["as_of_date"] = panel["as_of_date"].fillna(panel[col])
            panel = panel.drop(columns=[col])

    panel["has_level"] = panel["llm_level"].notna()
    panel["has_delta"] = panel["change_magnitude"].notna()
    panel["has_surprise"] = panel["surprise_magnitude"].notna()

    panel["level_quant_sign_match"] = panel.apply(
        lambda r: _same_sign(r.get("llm_level"), r.get("quant_z")), axis=1
    )
    panel["delta_quant_sign_match"] = panel.apply(
        lambda r: _same_sign(r.get("change_magnitude"), r.get("quant_z_delta")), axis=1
    )
    panel["is_divergence"] = panel["agrees_with_quant"].eq(False)
    panel["signal_stack"] = panel.apply(_signal_stack, axis=1)

    if not full_spine:
        mask = panel["has_level"] | panel["has_delta"] | panel["has_surprise"]
        panel = panel.loc[mask].copy()

    panel = panel.sort_values(["fiscal_period", "dimension"]).reset_index(drop=True)
    for col in PANEL_COLUMNS:
        if col not in panel.columns:
            panel[col] = None
    return panel[PANEL_COLUMNS]


def build_summary(panel: pd.DataFrame, ticker: str) -> dict:
    diverges = panel.loc[panel["is_divergence"] == True]  # noqa: E712
    top = (
        diverges.assign(abs_gap=diverges["narrative_quant_gap"].abs())
        .sort_values("abs_gap", ascending=False)
        .head(10)
    )
    top_rows = [
        {
            "fiscal_period": r["fiscal_period"],
            "dimension": r["dimension"],
            "llm_level": r["llm_level"],
            "quant_z": r["quant_z"],
            "surprise_magnitude": r["surprise_magnitude"],
            "narrative_quant_gap": r["narrative_quant_gap"],
        }
        for _, r in top.iterrows()
    ]
    return {
        "ticker": ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": int(len(panel)),
        "coverage": {
            "has_level": int(panel["has_level"].sum()),
            "has_delta": int(panel["has_delta"].sum()),
            "has_surprise": int(panel["has_surprise"].sum()),
            "is_divergence": int(panel["is_divergence"].sum()),
        },
        "fiscal_periods": sorted(panel["fiscal_period"].unique().tolist()),
        "dimensions": ALL_DIMENSIONS,
        "top_divergences": top_rows,
    }


# --- HTML report ---

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


def render_row(row: pd.Series, row_id: int) -> str:
    dim = row["dimension"]
    label = DIM_LABELS.get(dim, dim.replace("_", " ").title())
    flags = []
    if row.get("is_divergence"):
        flags.append('<span class="flag diverge">quant diverges</span>')
    if not row.get("has_delta"):
        flags.append('<span class="flag missing">no delta</span>')
    stack = row.get("signal_stack") or ""
    if stack:
        flags.append(f'<span class="flag stack" title="{esc(stack)}">{esc(stack[:48])}{"…" if len(stack) > 48 else ""}</span>')

    cd = row.get("change_direction")
    delta_txt = "&mdash;"
    if pd.notna(row.get("change_magnitude")):
        delta_txt = f"{DELTA_DIR_LABELS.get(cd, cd or '')} {fmt_score(row.get('change_magnitude'))}"

    sd = row.get("surprise_direction")
    surpr_txt = "&mdash;"
    if pd.notna(row.get("surprise_magnitude")):
        surpr_txt = f"{SURPRISE_DIR_LABELS.get(sd, sd or '')} {fmt_score(row.get('surprise_magnitude'))}"

    details = []
    for key, title in (
        ("level_rationale", "Focus 1 — Level"),
        ("delta_rationale", "Focus 2 — Delta"),
        ("surprise_rationale", "Focus 3 — Surprise"),
    ):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            details.append(f"<div class=\"detail\"><strong>{esc(title)}</strong><p>{esc(val)}</p></div>")

    details_html = f"<div class=\"details\">{''.join(details)}</div>" if details else ""

    return f"""
    <tr class="data-row" data-q="{esc(row['fiscal_period'])}" data-div="{1 if row.get('is_divergence') else 0}"
        data-delta-missing="{0 if row.get('has_delta') else 1}">
      <td class="fp">{esc(row['fiscal_period'])}</td>
      <td class="dim">{esc(label)}</td>
      <td class="num" style="{mag_tint(row.get('llm_level'))}">{fmt_score(row.get('llm_level'))}</td>
      <td class="num" style="{mag_tint(row.get('change_magnitude'))}">{delta_txt}</td>
      <td class="num" style="{mag_tint(row.get('surprise_magnitude'))}">{surpr_txt}</td>
      <td class="num z" style="{mag_tint(row.get('quant_z'), hi=1.5)}">{fmt_z(row.get('quant_z'))}</td>
      <td class="num gap" style="{mag_tint(row.get('narrative_quant_gap'), hi=2.0)}">{fmt_z(row.get('narrative_quant_gap'))}</td>
      <td class="flags">{''.join(flags)}</td>
      <td class="expand"><button type="button" class="toggle" aria-expanded="false" data-target="row-{row_id}">+</button></td>
    </tr>
    <tr class="detail-row" id="row-{row_id}" hidden><td colspan="9">{details_html}</td></tr>
    """


def build_html(panel: pd.DataFrame, summary: dict) -> str:
    ticker = summary.get("ticker", "")
    cov = summary.get("coverage", {})
    generated = esc(summary.get("generated_at", ""))
    periods = summary.get("fiscal_periods", [])

    buttons = ['<button class="fbtn active" data-filter="ALL">All</button>']
    for fp in periods:
        buttons.append(f'<button class="fbtn" data-filter="q:{esc(fp)}">{esc(fp)}</button>')
    buttons.append('<button class="fbtn" data-filter="div">Diverges only</button>')
    buttons.append('<button class="fbtn" data-filter="nodelta">Missing delta</button>')

    rows_html = "".join(render_row(row, i) for i, (_, row) in enumerate(panel.iterrows()))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(ticker)} Feature Panel</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; padding: 24px; line-height: 1.45; color: #1c1c1e; background: #fff; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: 13px; margin-bottom: 18px; }}
  .stats {{ font-size: 13px; margin-bottom: 12px; }}
  .controls {{ position: sticky; top: 0; background: #fff; padding: 10px 0;
              border-bottom: 1px solid #e5e5e5; margin-bottom: 16px; z-index: 5; }}
  .fbtn {{ font-size: 13px; padding: 6px 12px; margin: 0 6px 6px 0; border: 1px solid #ccc;
          border-radius: 6px; background: #f7f7f7; cursor: pointer; }}
  .fbtn.active {{ background: #1c1c1e; color: #fff; border-color: #1c1c1e; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #e2e2e2; padding: 8px 10px; vertical-align: top; text-align: left; }}
  th {{ background: #f2f2f4; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }}
  td.dim {{ font-weight: 600; white-space: nowrap; }}
  td.num {{ text-align: center; font-variant-numeric: tabular-nums; font-weight: 600; width: 10%; }}
  td.flags {{ width: 18%; font-size: 11px; }}
  .flag {{ display: inline-block; margin: 1px 3px 1px 0; padding: 1px 6px; border-radius: 4px;
           text-transform: uppercase; letter-spacing: .03em; font-size: 10px; }}
  .flag.diverge {{ color: #7a4a12; background: #fbf0df; border: 1px solid #eed6ab; }}
  .flag.missing {{ color: #555; background: #f0f0f0; border: 1px solid #ddd; }}
  .flag.stack {{ color: #334; background: #eef2f7; border: 1px solid #ccd6e0; text-transform: none; }}
  .toggle {{ font-size: 14px; width: 28px; height: 28px; border: 1px solid #ccc; border-radius: 4px;
            background: #f7f7f7; cursor: pointer; }}
  .details {{ padding: 8px 4px; }}
  .detail {{ margin-bottom: 10px; }}
  .detail p {{ margin: 4px 0 0; color: #333; }}
  tr.detail-row td {{ background: #fafafa; }}
  .legend {{ font-size: 11px; color: #777; margin-top: 8px; }}
</style>
</head>
<body>
  <h1>{esc(ticker)} Unified Feature Panel</h1>
  <div class="sub">Focus 1 level + Focus 2 delta + Focus 3 surprise + quant spine. Generated {generated}. See feature_panel_reference_key.txt.</div>
  <div class="stats">Coverage: {cov.get('has_level', 0)} level &middot; {cov.get('has_delta', 0)} delta &middot;
    {cov.get('has_surprise', 0)} surprise &middot; {cov.get('is_divergence', 0)} diverges &middot; {summary.get('row_count', 0)} rows</div>
  <div class="controls">{''.join(buttons)}
    <div class="legend">Click + to expand rationales. Gap = surprise magnitude minus quant z (from Focus 3 scorer).</div>
  </div>
  <table>
    <thead>
      <tr><th>Quarter</th><th>Dimension</th><th>Level</th><th>Delta</th><th>Surprise</th>
          <th>Quant z</th><th>Gap</th><th>Flags</th><th></th></tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
<script>
(function () {{
  var filter = 'ALL';
  var btns = document.querySelectorAll('.fbtn');
  var dataRows = document.querySelectorAll('tr.data-row');

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
  }}

  btns.forEach(function (b) {{
    b.addEventListener('click', function () {{
      filter = b.getAttribute('data-filter');
      applyFilter();
    }});
  }});

  document.querySelectorAll('.toggle').forEach(function (btn) {{
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
</script>
</body>
</html>
"""


def write_outputs(panel: pd.DataFrame, summary: dict, ticker: str) -> None:
    base = OUT_DIR / f"{ticker}_feature_panel"
    panel.to_csv(base.with_suffix(".csv"), index=False)
    try:
        panel.to_parquet(base.with_suffix(".parquet"), index=False)
    except Exception as exc:
        print(f"  ! parquet write skipped: {exc}")

    summary_path = OUT_DIR / f"{ticker}_feature_panel_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    html_path = OUT_DIR / f"{ticker}_feature_panel_report.html"
    html_path.write_text(build_html(panel, summary), encoding="utf-8")

    print(f"Wrote {base.with_suffix('.csv')}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {html_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build unified narrative feature panel.")
    parser.add_argument("--ticker", default="AMZN", help="Ticker prefix for input/output files.")
    parser.add_argument(
        "--full-spine",
        action="store_true",
        help="Include all quant-spine quarters (sparse LLM columns).",
    )
    parser.add_argument(
        "--llm-only",
        action="store_true",
        help="Build panel from LLM scores when quant dimension_scores are missing.",
    )
    args = parser.parse_args()
    ticker = args.ticker.upper()

    try:
        level = _read(f"{ticker}_llm_dimension_scores")
        delta = _read(f"{ticker}_dimension_delta")
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    quant = _read_optional(f"{ticker}_dimension_scores")
    surprise_df = _read_optional(f"{ticker}_dimension_surprise")
    if surprise_df is None:
        surprise_df = pd.DataFrame(
            columns=[
                "ticker",
                "fiscal_period",
                "dimension",
                "as_of_date",
                "surprise_direction",
                "surprise_magnitude",
                "agrees_with_quant",
                "narrative_quant_gap",
                "rationale",
                "n_evidence_verified",
                "n_evidence",
                "evidence_verified",
            ]
        )

    if quant is not None and not args.llm_only:
        spine = build_spine(quant, ticker)
    elif args.llm_only or quant is None:
        if quant is None and not args.llm_only:
            print(
                f"Note: {ticker}_dimension_scores not found; building LLM-only panel "
                "(quant/surprise columns will be sparse).",
                file=sys.stderr,
            )
        spine = build_spine_from_level(prepare_level(level), ticker)
    else:
        print(f"Error: missing {ticker}_dimension_scores.csv", file=sys.stderr)
        return 1

    panel = merge_panel(
        spine,
        prepare_level(level),
        prepare_delta(delta),
        prepare_surprise(surprise_df),
        full_spine=args.full_spine,
    )
    summary = build_summary(panel, ticker)
    write_outputs(panel, summary, ticker)

    cov = summary["coverage"]
    print(f"\n{ticker} feature panel: {summary['row_count']} rows")
    print(f"  level={cov['has_level']}  delta={cov['has_delta']}  surprise={cov['has_surprise']}  diverges={cov['is_divergence']}")
    if summary["top_divergences"]:
        print("\nTop divergences (|gap|):")
        for r in summary["top_divergences"][:5]:
            print(
                f"  {r['fiscal_period']} {r['dimension']}: "
                f"level={r['llm_level']:+.1f} quant_z={r['quant_z']:+.2f} gap={r['narrative_quant_gap']:+.2f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
