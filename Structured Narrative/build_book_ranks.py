#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build cross-sectional book ranks for the frozen production signal pack.

    python "Structured Narrative/build_book_ranks.py" --tickers MSFT AAPL NVDA MU
    python "Structured Narrative/build_book_ranks.py" --trigger-ticker OPAL --trigger-period FY2026-Q1
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from company_config import PILOT_TICKERS  # noqa: E402
from export_modeling_spine import filter_registry_complete, load_panel  # noqa: E402
from output_paths import cross_company_artifact, ensure_cross_company_tree  # noqa: E402
from period_dates import (  # noqa: E402
    apply_feature_availability_dates,
    apply_investable_cross_section_columns,
    enrich_panel_period_columns,
    to_date,
)
from signal_pack import DEFAULT_PACK_PATH, SignalPack, load_signal_pack  # noqa: E402
from spine_export import standardize_surprise_novelty_exclusivity  # noqa: E402

RankMode = Literal["investable_asof", "call_day"]
DEFAULT_RANK_MODE: RankMode = "investable_asof"

# Human-facing column order for CSV / HTML (machine schema stays on parquet).
CSV_DISPLAY_COLUMNS: list[tuple[str, str]] = [
    ("ticker", "Ticker"),
    ("fiscal_period", "Fiscal period"),
    ("period_bucket", "Period bucket"),
    ("as_of_date", "As-of date"),
    ("rank_mode", "Rank mode"),
    ("signal", "Signal"),
    ("dimension", "Dimension"),
    ("hypothesis", "Hypothesis"),
    ("rank", "Rank (1=highest)"),
    ("cs_z", "Cross-section z"),
    ("raw", "Raw signal"),
    ("n_peers", "Peer count"),
    ("eligible", "Eligible"),
    ("pack_id", "Pack"),
    ("trigger_ticker", "Trigger ticker"),
    ("trigger_period", "Trigger period"),
    ("built_at", "Built at (UTC)"),
]

METRIC_KEY: list[tuple[str, str]] = [
    (
        "As-of date",
        "Common investable-as-of date for the period bucket (latest peer T+7 / "
        "model_date). Official ranks publish only when this date is ≤ today.",
    ),
    (
        "Rank mode",
        "investable_asof (default): peer set = names with features available by "
        "as-of. call_day: legacy latest-available peers (provisional).",
    ),
    (
        "Rank (1=highest)",
        "Dense rank of the signal within eligible peers for this hypothesis. "
        "1 is the strongest / highest value.",
    ),
    (
        "Cross-section z",
        "Z-score of the raw signal versus other eligible names in the same "
        "period bucket (mean 0, std 1 within that peer set).",
    ),
    (
        "Raw signal",
        "Call-day feature value used for ranking (e.g. quant_z_pit or "
        "agrees_with_quant) for that ticker × dimension.",
    ),
    (
        "Peer count",
        "Number of eligible book names that entered the cross-section for "
        "this hypothesis (must be ≥ min_names, usually 3).",
    ),
    (
        "Eligible",
        "False when excluded (first-print, missing prior, features not available "
        "by as-of, not investable_ready, or missing signal).",
    ),
    (
        "Period bucket",
        "Calendar quarter of period end used to define the peer set "
        "(period_end_calendar_quarter).",
    ),
    (
        "Pack",
        "Frozen production signal pack id (production_v1). Bump when "
        "hypotheses change intentionally.",
    ),
]


def _finite(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def stack_book_panels(tickers: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for ticker in tickers:
        key = ticker.strip().upper()
        try:
            panel = load_panel(key)
        except FileNotFoundError:
            continue
        panel = filter_registry_complete(panel, key)
        if panel.empty:
            continue
        panel = panel.copy()
        panel["ticker"] = key
        panel = enrich_panel_period_columns(panel)
        panel = apply_feature_availability_dates(panel)
        panel = standardize_surprise_novelty_exclusivity(panel)
        frames.append(panel)
    if not frames:
        return pd.DataFrame()
    stacked = pd.concat(frames, ignore_index=True)
    return apply_investable_cross_section_columns(stacked)


def _row_eligible(
    row: pd.Series,
    *,
    mode: RankMode,
    as_of: date | None,
) -> bool:
    reason = row.get("exclusion_reason")
    if reason is not None and str(reason).strip() and str(reason).strip().lower() not in {
        "nan",
        "none",
        "",
    }:
        return False
    if bool(row.get("first_print")) or bool(row.get("no_prior")):
        return False
    if mode == "investable_asof":
        if as_of is None:
            return False
        call = to_date(row.get("call_feature_available_date"))
        if call is None or call > as_of:
            return False
        if "investable_ready" in row.index and pd.notna(row.get("investable_ready")):
            if not bool(row.get("investable_ready")):
                return False
        return True
    # call_day: prefer investable_ready when present, else allow.
    if "investable_ready" in row.index and pd.notna(row.get("investable_ready")):
        if not bool(row.get("investable_ready")):
            return False
    return True


def _bucket_as_of_date(bucket_rows: pd.DataFrame) -> date | None:
    if bucket_rows.empty:
        return None
    if "investable_as_of_date" in bucket_rows.columns:
        for value in bucket_rows["investable_as_of_date"].dropna():
            parsed = to_date(value)
            if parsed is not None:
                return parsed
    # Fallback: recompute from stacked investable helper already applied.
    return None


def _resolve_period_bucket(
    stacked: pd.DataFrame,
    *,
    bucket_col: str,
    trigger_ticker: str | None,
    trigger_period: str | None,
) -> str | None:
    if stacked.empty or bucket_col not in stacked.columns:
        return None
    if trigger_ticker and trigger_period:
        mask = (stacked["ticker"].astype(str).str.upper() == trigger_ticker.upper()) & (
            stacked["fiscal_period"].astype(str).str.upper() == trigger_period.upper()
        )
        values = stacked.loc[mask, bucket_col].dropna().astype(str)
        if len(values):
            return str(values.iloc[0])
    # Latest common bucket by lexical calendar quarter (yyyy-Qn sorts poorly for Q10
    # but fine for Q1-Q4). Prefer max earnings_date if present.
    work = stacked.dropna(subset=[bucket_col]).copy()
    if work.empty:
        return None
    if "earnings_date" in work.columns:
        work["_ed"] = pd.to_datetime(work["earnings_date"], errors="coerce")
        work = work.sort_values("_ed")
        return str(work[bucket_col].iloc[-1])
    return str(sorted(work[bucket_col].astype(str).unique())[-1])


def _cross_section_z_and_rank(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    arr = values.astype(float)
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=0))
    if sigma == 0 or math.isnan(sigma):
        z = pd.Series(0.0, index=arr.index)
    else:
        z = (arr - mu) / sigma
    # Dense rank: 1 = highest signal
    rank = z.rank(method="dense", ascending=False).astype(int)
    return z, rank


def build_book_ranks(
    tickers: list[str],
    *,
    pack: SignalPack | None = None,
    trigger_ticker: str | None = None,
    trigger_period: str | None = None,
    now: datetime | None = None,
    mode: RankMode = DEFAULT_RANK_MODE,
    force_asof: bool = False,
    stacked: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    pack = pack or load_signal_pack()
    if mode not in ("investable_asof", "call_day"):
        raise ValueError(f"Unknown rank mode: {mode!r}")
    built_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = built_at.date()
    summary: dict[str, Any] = {
        "pack_id": pack.pack_id,
        "rank_method": pack.rank_method,
        "rank_mode": mode,
        "period_bucket_col": pack.period_bucket,
        "period_bucket": None,
        "as_of_date": None,
        "min_names": pack.min_names,
        "n_tickers_requested": len(tickers),
        "n_tickers_loaded": 0,
        "n_peers": 0,
        "n_rows": 0,
        "trigger_ticker": (trigger_ticker or "").upper() or None,
        "trigger_period": (trigger_period or "").upper() or None,
        "built_at": built_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "skipped_reason": None,
        "pending": False,
        "prior_built_at": None,
        "preserve_prior_artifacts": False,
    }
    stacked = (
        stacked
        if stacked is not None
        else stack_book_panels([t.upper() for t in tickers])
    )
    summary["n_tickers_loaded"] = (
        int(stacked["ticker"].nunique()) if not stacked.empty and "ticker" in stacked.columns else 0
    )
    if stacked.empty:
        summary["skipped_reason"] = "no_panels"
        return pd.DataFrame(), summary

    bucket_col = pack.period_bucket
    period_bucket = _resolve_period_bucket(
        stacked,
        bucket_col=bucket_col,
        trigger_ticker=trigger_ticker,
        trigger_period=trigger_period,
    )
    summary["period_bucket"] = period_bucket
    if not period_bucket:
        summary["skipped_reason"] = "no_period_bucket"
        return pd.DataFrame(), summary

    bucket_rows = stacked[stacked[bucket_col].astype(str) == str(period_bucket)].copy()
    as_of = _bucket_as_of_date(bucket_rows)
    summary["as_of_date"] = as_of.isoformat() if as_of is not None else None

    if mode == "investable_asof":
        if as_of is None:
            summary["skipped_reason"] = "no_asof_date"
            return pd.DataFrame(), summary
        if as_of > today and not force_asof:
            summary["skipped_reason"] = "awaiting_investable_asof"
            summary["pending"] = True
            summary["preserve_prior_artifacts"] = True
            return pd.DataFrame(), summary

    rows_out: list[dict[str, Any]] = []
    peer_counts: list[int] = []
    as_of_iso = as_of.isoformat() if as_of is not None else None

    for hyp in pack.iter_hypotheses():
        signal = hyp["signal"]
        dimension = hyp["dimension"]
        if signal not in bucket_rows.columns or "dimension" not in bucket_rows.columns:
            continue
        dim_rows = bucket_rows[bucket_rows["dimension"].astype(str) == dimension].copy()
        if dim_rows.empty:
            continue
        # One row per ticker (latest fiscal_period if duplicates).
        dim_rows = dim_rows.sort_values(["ticker", "fiscal_period"])
        dim_rows = dim_rows.groupby("ticker", as_index=False).tail(1)
        dim_rows["_raw"] = dim_rows[signal].map(_finite)
        dim_rows["_eligible"] = (
            dim_rows.apply(
                lambda row: _row_eligible(row, mode=mode, as_of=as_of),
                axis=1,
            )
            & dim_rows["_raw"].notna()
        )
        peers = dim_rows[dim_rows["_eligible"]].copy()
        n_peers = int(len(peers))
        peer_counts.append(n_peers)
        if n_peers < pack.min_names:
            continue
        z, rank = _cross_section_z_and_rank(peers["_raw"])
        peers = peers.assign()
        peers["_cs_z"] = z
        peers["_rank"] = rank
        for _, row in peers.iterrows():
            rows_out.append(
                {
                    "pack_id": pack.pack_id,
                    "rank_mode": mode,
                    "as_of_date": as_of_iso,
                    "period_bucket": period_bucket,
                    "ticker": str(row["ticker"]).upper(),
                    "fiscal_period": str(row.get("fiscal_period") or ""),
                    "signal": signal,
                    "dimension": dimension,
                    "hypothesis": hyp.get("hypothesis") or "",
                    "raw": float(row["_raw"]),
                    "cs_z": round(float(row["_cs_z"]), 6),
                    "rank": int(row["_rank"]),
                    "n_peers": n_peers,
                    "eligible": True,
                    "trigger_ticker": summary["trigger_ticker"],
                    "trigger_period": summary["trigger_period"],
                    "built_at": summary["built_at"],
                }
            )
        # Ineligible names present in the bucket for this dimension.
        ineligible = dim_rows[~dim_rows["_eligible"]]
        for _, row in ineligible.iterrows():
            rows_out.append(
                {
                    "pack_id": pack.pack_id,
                    "rank_mode": mode,
                    "as_of_date": as_of_iso,
                    "period_bucket": period_bucket,
                    "ticker": str(row["ticker"]).upper(),
                    "fiscal_period": str(row.get("fiscal_period") or ""),
                    "signal": signal,
                    "dimension": dimension,
                    "hypothesis": hyp.get("hypothesis") or "",
                    "raw": _finite(row.get("_raw")),
                    "cs_z": None,
                    "rank": None,
                    "n_peers": n_peers,
                    "eligible": False,
                    "trigger_ticker": summary["trigger_ticker"],
                    "trigger_period": summary["trigger_period"],
                    "built_at": summary["built_at"],
                }
            )

    if not rows_out:
        summary["skipped_reason"] = (
            "below_min_names"
            if peer_counts and max(peer_counts) < pack.min_names
            else "no_rank_rows"
        )
        summary["n_peers"] = max(peer_counts) if peer_counts else 0
        return pd.DataFrame(), summary

    frame = pd.DataFrame(rows_out)
    eligible = frame[frame["eligible"] == True]  # noqa: E712
    summary["n_peers"] = int(eligible["n_peers"].max()) if not eligible.empty else 0
    summary["n_rows"] = int(len(frame))
    summary["pending"] = False
    return frame, summary


def frame_for_readable_csv(frame: pd.DataFrame) -> pd.DataFrame:
    """Display CSV: clear headers + metric key columns on the right."""
    if frame.empty:
        cols = [label for _, label in CSV_DISPLAY_COLUMNS] + ["", "Metric", "Meaning"]
        return pd.DataFrame(columns=cols)

    work = frame.copy()
    # Prefer eligible / stronger ranks first for human scanning.
    if "eligible" in work.columns:
        work["_el"] = work["eligible"].map(lambda v: 0 if bool(v) else 1)
    else:
        work["_el"] = 0
    work["_rank_sort"] = pd.to_numeric(work.get("rank"), errors="coerce").fillna(10**9)
    work = work.sort_values(
        ["dimension", "signal", "_el", "_rank_sort", "ticker"],
        kind="mergesort",
    ).drop(columns=["_el", "_rank_sort"])

    out = pd.DataFrame()
    for src, label in CSV_DISPLAY_COLUMNS:
        if src in work.columns:
            out[label] = work[src].values
        else:
            out[label] = None

    # Blank spacer + key legend aligned to the right of the data block.
    out[""] = ""
    out["Metric"] = ""
    out["Meaning"] = ""
    for index, (metric, meaning) in enumerate(METRIC_KEY):
        if index >= len(out):
            break
        out.iloc[index, out.columns.get_loc("Metric")] = metric
        out.iloc[index, out.columns.get_loc("Meaning")] = meaning
    return out


def _html_escape(value: Any) -> str:
    text = "" if value is None or (isinstance(value, float) and math.isnan(value)) else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_book_ranks_html(frame: pd.DataFrame, summary: dict[str, Any]) -> str:
    """Self-contained filterable ranks table with a metrics key sidebar."""
    pack = summary.get("pack_id") or "—"
    bucket = summary.get("period_bucket") or "—"
    built = summary.get("built_at") or "—"
    as_of = summary.get("as_of_date") or "—"
    rank_mode = summary.get("rank_mode") or "—"
    n_peers = summary.get("n_peers")
    trigger = summary.get("trigger_ticker") or ""
    trigger_period = summary.get("trigger_period") or ""
    pending = bool(summary.get("pending"))

    key_items = "".join(
        f"<dt>{_html_escape(metric)}</dt><dd>{_html_escape(meaning)}</dd>"
        for metric, meaning in METRIC_KEY
    )

    hyp_options = ['<option value="">All hypotheses</option>']
    if not frame.empty:
        pairs = sorted(
            {
                (str(r.get("signal") or ""), str(r.get("dimension") or ""))
                for r in frame.to_dict(orient="records")
                if r.get("signal") and r.get("dimension")
            }
        )
        for signal, dimension in pairs:
            value = f"{signal}|{dimension}"
            label = f"{signal} × {dimension}"
            hyp_options.append(
                f'<option value="{_html_escape(value)}">{_html_escape(label)}</option>'
            )

    body_rows: list[str] = []
    # Interactive rows from machine frame (stable attrs); CSV uses readable layout.
    rows = [] if frame.empty else frame.to_dict(orient="records")
    rows = sorted(
        rows,
        key=lambda r: (
            str(r.get("dimension") or ""),
            str(r.get("signal") or ""),
            0 if r.get("eligible") in (True, "True", "true", 1) else 1,
            float(r["rank"])
            if r.get("rank") not in (None, "") and str(r.get("rank")) != "nan"
            else 1e9,
            str(r.get("ticker") or ""),
        ),
    )
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        eligible = row.get("eligible") in (True, "True", "true", 1)
        is_trigger = bool(trigger) and ticker == str(trigger).upper()
        rank = row.get("rank")
        cs_z = row.get("cs_z")
        raw = row.get("raw")

        def _num(v: Any, digits: int = 3) -> str:
            try:
                if v is None or str(v) == "nan":
                    return "—"
                return f"{float(v):.{digits}f}"
            except (TypeError, ValueError):
                return "—"

        rank_s = "—" if rank is None or str(rank) == "nan" else str(int(float(rank)))
        cls = []
        if is_trigger:
            cls.append("trigger")
        if not eligible:
            cls.append("ineligible")
        body_rows.append(
            "<tr"
            f' data-signal="{_html_escape(row.get("signal"))}"'
            f' data-dimension="{_html_escape(row.get("dimension"))}"'
            f' data-ticker="{_html_escape(ticker)}"'
            f' data-eligible="{"1" if eligible else "0"}"'
            f' class="{" ".join(cls)}">'
            f"<td>{'→ ' if is_trigger else ''}{_html_escape(ticker)}</td>"
            f"<td>{_html_escape(row.get('fiscal_period'))}</td>"
            f"<td>{_html_escape(row.get('signal'))} × {_html_escape(row.get('dimension'))}</td>"
            f'<td class="num">{_html_escape(rank_s)}</td>'
            f'<td class="num">{_html_escape(_num(cs_z))}</td>'
            f'<td class="num">{_html_escape(_num(raw))}</td>'
            f'<td class="num">{_html_escape(row.get("n_peers") if row.get("n_peers") is not None else "—")}</td>'
            f"<td>{'yes' if eligible else 'no'}</td>"
            "</tr>"
        )

    rows_html = "\n".join(body_rows) if body_rows else (
        '<tr><td colspan="8">No rank rows (peer set below min_names or missing panels).</td></tr>'
    )
    trigger_note = ""
    if trigger:
        trigger_note = (
            f" · trigger {_html_escape(trigger)} {_html_escape(trigger_period)}"
        ).rstrip()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Book ranks — {_html_escape(pack)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #fafafa; color: #1a1a1a; }}
  .wrap {{ display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 20px;
           max-width: 1280px; margin: 0 auto; padding: 20px 24px 40px; }}
  h1 {{ font-size: 22px; font-weight: 650; margin: 0 0 6px; }}
  .meta {{ font-size: 13px; color: #555; margin-bottom: 14px; }}
  .controls {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: end; margin-bottom: 12px; }}
  label {{ font-size: 12px; color: #555; display: flex; flex-direction: column; gap: 4px; }}
  select, input[type="search"] {{ font-size: 13px; padding: 7px 10px; border: 1px solid #ccc;
    border-radius: 6px; background: #fff; min-width: 160px; }}
  .check {{ flex-direction: row; align-items: center; gap: 6px; padding-bottom: 8px; }}
  .count {{ font-size: 12px; color: #666; margin: 0 0 8px; }}
  .table-scroll {{ overflow: auto; border: 1px solid #ddd; border-radius: 8px; background: #fff; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th {{ position: sticky; top: 0; background: #f3f3f3; text-align: left; padding: 8px 10px;
       border-bottom: 1px solid #ddd; font-weight: 600; cursor: pointer; user-select: none; }}
  th:hover {{ background: #ebebeb; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #eee; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr.trigger td {{ background: #fff8e6; font-weight: 600; }}
  tr.ineligible td {{ color: #888; }}
  tr.hidden {{ display: none; }}
  aside {{ position: sticky; top: 16px; align-self: start; background: #fff;
           border: 1px solid #ddd; border-radius: 8px; padding: 14px 16px; }}
  aside h2 {{ font-size: 14px; margin: 0 0 10px; }}
  aside dl {{ margin: 0; }}
  aside dt {{ font-size: 12px; font-weight: 650; margin-top: 10px; }}
  aside dd {{ margin: 3px 0 0; font-size: 12px; color: #444; line-height: 1.4; }}
  @media (max-width: 900px) {{
    .wrap {{ grid-template-columns: 1fr; }}
    aside {{ position: static; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <main>
    <h1>Book ranks{" (pending as-of)" if pending else ""}</h1>
    <div class="meta">pack={_html_escape(pack)} · mode={_html_escape(rank_mode)} ·
      period_bucket={_html_escape(bucket)} · as_of={_html_escape(as_of)} ·
      n_peers={_html_escape(n_peers if n_peers is not None else "—")} ·
      built_at={_html_escape(built)}{trigger_note}</div>
    <div class="controls">
      <label>Hypothesis
        <select id="hyp">{"".join(hyp_options)}</select>
      </label>
      <label>Ticker contains
        <input id="q" type="search" placeholder="e.g. MSFT" autocomplete="off"/>
      </label>
      <label class="check"><input id="eligible-only" type="checkbox" checked/> Eligible only</label>
    </div>
    <p class="count" id="count"></p>
    <div class="table-scroll">
      <table id="ranks">
        <thead>
          <tr>
            <th data-col="0">Ticker</th>
            <th data-col="1">Fiscal period</th>
            <th data-col="2">Hypothesis</th>
            <th data-col="3">Rank</th>
            <th data-col="4">Cross-section z</th>
            <th data-col="5">Raw signal</th>
            <th data-col="6">Peers</th>
            <th data-col="7">Eligible</th>
          </tr>
        </thead>
        <tbody>
{rows_html}
        </tbody>
      </table>
    </div>
  </main>
  <aside>
    <h2>Metric key</h2>
    <dl>{key_items}</dl>
  </aside>
</div>
<script>
(function () {{
  var hyp = document.getElementById('hyp');
  var q = document.getElementById('q');
  var elig = document.getElementById('eligible-only');
  var count = document.getElementById('count');
  var table = document.getElementById('ranks');
  var sortCol = 3;
  var sortAsc = true;

  function applyFilters() {{
    var hypVal = (hyp.value || '');
    var query = (q.value || '').trim().toUpperCase();
    var onlyElig = elig.checked;
    var shown = 0, total = 0;
    table.querySelectorAll('tbody tr').forEach(function (tr) {{
      if (!tr.getAttribute('data-ticker')) return;
      total += 1;
      var signal = tr.getAttribute('data-signal') || '';
      var dimension = tr.getAttribute('data-dimension') || '';
      var ticker = (tr.getAttribute('data-ticker') || '').toUpperCase();
      var eligible = tr.getAttribute('data-eligible') === '1';
      var hypOk = !hypVal || hypVal === (signal + '|' + dimension);
      var qOk = !query || ticker.indexOf(query) !== -1;
      var eOk = !onlyElig || eligible;
      var ok = hypOk && qOk && eOk;
      tr.classList.toggle('hidden', !ok);
      if (ok) shown += 1;
    }});
    count.textContent = 'Showing ' + shown + ' of ' + total + ' rows';
  }}

  function sortBy(col) {{
    if (sortCol === col) sortAsc = !sortAsc; else {{ sortCol = col; sortAsc = col !== 3; }}
    var tbody = table.tBodies[0];
    var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
    rows.sort(function (a, b) {{
      var av = (a.children[col] && a.children[col].textContent || '').trim();
      var bv = (b.children[col] && b.children[col].textContent || '').trim();
      var an = parseFloat(av), bn = parseFloat(bv);
      var cmp;
      if (!isNaN(an) && !isNaN(bn) && av !== '—' && bv !== '—') cmp = an - bn;
      else cmp = av.localeCompare(bv);
      return sortAsc ? cmp : -cmp;
    }});
    rows.forEach(function (r) {{ tbody.appendChild(r); }});
  }}

  hyp.addEventListener('change', applyFilters);
  q.addEventListener('input', applyFilters);
  elig.addEventListener('change', applyFilters);
  table.querySelectorAll('th[data-col]').forEach(function (th) {{
    th.addEventListener('click', function () {{ sortBy(parseInt(th.getAttribute('data-col'), 10)); }});
  }});
  applyFilters();
}})();
</script>
</body>
</html>
"""


def write_book_ranks(
    frame: pd.DataFrame,
    summary: dict[str, Any],
) -> dict[str, str]:
    ensure_cross_company_tree()
    csv_path = cross_company_artifact("csv", "book_ranks", "csv", mkdir=True)
    parquet_path = cross_company_artifact("parquet", "book_ranks", "parquet", mkdir=True)
    json_path = cross_company_artifact("json", "book_ranks_summary", "json", mkdir=True)
    html_path = cross_company_artifact("reports", "book_ranks", "html", mkdir=True)
    if json_path.is_file():
        try:
            prior = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(prior, dict) and prior.get("built_at"):
                summary["prior_built_at"] = prior.get("built_at")
        except (OSError, json.JSONDecodeError):
            pass
    if frame.empty:
        summary["paths"] = {
            "csv": str(csv_path),
            "parquet": str(parquet_path),
            "summary": str(json_path),
            "html": str(html_path),
        }
        # Awaiting as-of: keep last good ranks table; only refresh summary.
        if summary.get("preserve_prior_artifacts") and (
            csv_path.is_file() or parquet_path.is_file()
        ):
            json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            return summary["paths"]
        json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        html_path.write_text(build_book_ranks_html(frame, summary), encoding="utf-8")
        return summary["paths"]

    # Parquet keeps the machine schema; CSV is the human-readable workbook view.
    try:
        frame.to_parquet(parquet_path, index=False)
    except Exception:
        parquet_path = Path("")
    readable = frame_for_readable_csv(frame)
    html_path.write_text(build_book_ranks_html(frame, summary), encoding="utf-8")
    # Write CSV via temp + replace so Excel locks surface as a clear rename error
    # rather than a half-written file.
    tmp_csv = csv_path.with_suffix(".csv.tmp")
    readable.to_csv(tmp_csv, index=False)
    try:
        tmp_csv.replace(csv_path)
    except OSError:
        # File may be open in Excel; leave .tmp beside the locked original.
        summary["csv_write_warning"] = (
            f"Could not replace {csv_path.name} (file locked?). "
            f"Wrote {tmp_csv.name} instead — close Excel and re-run or rename."
        )
        csv_path = tmp_csv
    paths = {
        "csv": str(csv_path),
        "parquet": str(parquet_path) if parquet_path else "",
        "summary": str(json_path),
        "html": str(html_path),
    }
    summary["paths"] = paths
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build production book ranks (investable-as-of by default)."
    )
    ap.add_argument("--tickers", nargs="+", default=list(PILOT_TICKERS))
    ap.add_argument("--pack", type=Path, default=DEFAULT_PACK_PATH)
    ap.add_argument("--trigger-ticker", default=None)
    ap.add_argument("--trigger-period", default=None)
    ap.add_argument(
        "--mode",
        choices=("investable_asof", "call_day"),
        default=DEFAULT_RANK_MODE,
        help="investable_asof (default) waits for bucket T+7 as-of; call_day is provisional.",
    )
    ap.add_argument(
        "--force-asof",
        action="store_true",
        help="Build investable_asof ranks even when as_of_date is still in the future.",
    )
    args = ap.parse_args(argv)
    pack = load_signal_pack(args.pack)
    frame, summary = build_book_ranks(
        [t.upper() for t in args.tickers],
        pack=pack,
        trigger_ticker=args.trigger_ticker,
        trigger_period=args.trigger_period,
        mode=args.mode,
        force_asof=bool(args.force_asof),
    )
    paths = write_book_ranks(frame, summary)
    print(json.dumps({"summary": summary, "paths": paths}, indent=2))
    if summary.get("skipped_reason"):
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
