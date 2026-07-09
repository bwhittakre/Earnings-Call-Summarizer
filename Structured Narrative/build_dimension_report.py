#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-contained HTML report for the AMZN LLM dimension scores.
=============================================================

Reads ``output/AMZN_dimension_view.json`` (produced by run_dimension_scoring.py)
and writes a single, dependency-free ``output/AMZN_dimension_report.html`` that
opens in any browser (no Cursor / no network needed).

Features:
  * Filter by quarter (buttons: each FY2024 quarter + "All").
  * A proper table per quarter: Dimension | LLM score (-2.0..+2.0) | Quant z |
    Rationale. Score cells are tinted by sign/magnitude for quick scanning.
  * Rationale is bullet-pointed; each bullet carries a superscript note number
    that links to the verbatim excerpt in a per-quarter Notes section. Excerpts
    that could not be verified verbatim against the transcript are tagged.

    python "Structured Narrative/build_dimension_report.py"
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from company_config import get_company  # noqa: E402
from output_paths import company_artifact, resolve_read_required  # noqa: E402

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

# label + title shown for each verification status. "verbatim" gets no chip (it is
# the expected/default case); only "unverified" is styled as a warning.
STATUS_CHIPS = {
    "composite": ("composite", "Ellipsis-stitched quote — every fragment is verbatim in the transcript."),
    "anchored": ("anchored", "A supporting contiguous verbatim span was located in the transcript for this claim."),
    "paraphrased": ("paraphrased", "Faithful paraphrase/shortening — the rescue judge confirmed support and returned a verbatim quote."),
    "unverified": ("unverified", "No supporting span could be found in the transcript."),
}


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def status_of(ev: dict) -> str:
    """Backward-compatible status: fall back to verified flag if status absent."""
    status = ev.get("status")
    if status:
        return status
    return "verbatim" if ev.get("verified") else "unverified"


def status_chip(status: str) -> str:
    if status not in STATUS_CHIPS:
        return ""
    label, title = STATUS_CHIPS[status]
    return f' <span class="chip {esc(status)}" title="{esc(title)}">{esc(label)}</span>'


def score_tint(v: float | None, lo: float = -2.0, hi: float = 2.0) -> str:
    """Green for positive, red for negative, opacity scaled by magnitude."""
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    m = max(lo, min(hi, f))
    frac = min(1.0, abs(m) / hi) if hi else 0.0
    alpha = round(0.12 + 0.33 * frac, 3)
    rgb = "40,150,80" if f > 0 else ("200,60,60" if f < 0 else "130,130,130")
    return f"background-color: rgba({rgb},{alpha});"


def fmt_score(v: float | None) -> str:
    if v is None:
        return "&mdash;"
    return f"{float(v):+.1f}"


def fmt_z(v: float | None) -> str:
    if v is None:
        return "&mdash;"
    return f"{float(v):+.2f}"


def render_quarter(qi: int, q: dict, dim_order: list[str]) -> str:
    fp = q["fiscal_period"]
    by_dim = {d["dimension"]: d for d in q.get("dimensions", [])}
    ordered = [by_dim[d] for d in dim_order if d in by_dim]
    ordered += [d for d in q.get("dimensions", []) if d["dimension"] not in dim_order]

    note = 0
    rows_html: list[str] = []
    footnotes: list[str] = []

    for d in ordered:
        dim = d["dimension"]
        label = DIM_LABELS.get(dim, dim.replace("_", " ").title())
        score_cell = (
            f'<td class="score" style="{score_tint(d.get("score"))}">'
            f'{fmt_score(d.get("score"))}</td>'
        )
        if d.get("is_quant_comparable"):
            z = d.get("quant_z")
            z_cell = f'<td class="z" style="{score_tint(z)}">{fmt_z(z)}</td>'
        else:
            z_cell = '<td class="z na">&mdash;</td>'

        bullets: list[str] = []
        for ev in d.get("evidence", []):
            note += 1
            src_id = f"src-{qi}-{note}"
            fn_id = f"fn-{qi}-{note}"
            sup = (
                f'<sup class="ref" id="{src_id}">'
                f'<a href="#{fn_id}">{note}</a></sup>'
            )
            bullets.append(f"<li>{esc(ev.get('claim'))}{sup}</li>")
            status = status_of(ev)
            chip = status_chip(status)
            canon = ev.get("canonical")
            canon_html = ""
            if (
                status in ("anchored", "paraphrased")
                and canon
                and canon.strip() != (ev.get("excerpt") or "").strip()
            ):
                canon_html = (
                    f'<div class="canon">verbatim: &ldquo;{esc(canon)}&rdquo;</div>'
                )
            footnotes.append(
                f'<li id="{fn_id}">'
                f'<a class="back" href="#{src_id}">[{note}]</a> '
                f'&ldquo;{esc(ev.get("excerpt"))}&rdquo;{chip}{canon_html}</li>'
            )

        rationale = f'<div class="rat">{esc(d.get("rationale"))}</div>' if d.get("rationale") else ""
        bullets_html = f"<ul class=\"bul\">{''.join(bullets)}</ul>" if bullets else ""
        rows_html.append(
            f"<tr><td class=\"dim\">{esc(label)}</td>{score_cell}{z_cell}"
            f"<td class=\"rationale\">{rationale}{bullets_html}</td></tr>"
        )

    footnotes_html = (
        f'<div class="notes"><h3>Notes &mdash; transcript evidence</h3>'
        f'<ol>{"".join(footnotes)}</ol></div>'
        if footnotes else ""
    )

    meta = (
        f'as-of {esc(q.get("as_of_date") or q.get("earnings_date") or "n/a")} '
        f'&middot; source: {esc(q.get("source"))} '
        f'&middot; {esc(q.get("n_chars"))} chars '
        f'&middot; {esc(q.get("n_speakers"))} speakers '
        f'&middot; excerpts supported: {esc(q.get("pct_verified"))}%'
    )

    return f"""
    <section class="quarter" data-q="{esc(fp)}">
      <h2>{esc(fp)}</h2>
      <div class="meta">{meta}</div>
      <table>
        <thead>
          <tr><th>Dimension</th><th>LLM score</th><th>Quant z</th><th>Rationale</th></tr>
        </thead>
        <tbody>
          {''.join(rows_html)}
        </tbody>
      </table>
      {footnotes_html}
    </section>
    """


def build_html(view: dict) -> str:
    dim_order = view.get("dimension_order", list(DIM_LABELS.keys()))
    quarters = [
        q for q in view.get("quarters", [])
        if q.get("output_scope", False)
    ]
    ticker = view.get("ticker", "")
    company = view.get("company_name", "")

    buttons = ['<button class="qbtn active" data-target="ALL">All</button>']
    sections: list[str] = []
    for qi, q in enumerate(quarters):
        fp = q["fiscal_period"]
        buttons.append(f'<button class="qbtn" data-target="{esc(fp)}">{esc(fp)}</button>')
        sections.append(render_quarter(qi, q, dim_order))

    generated = esc(view.get("generated_at", ""))
    model = esc(view.get("model", ""))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(ticker)} FY2024 Narrative Dimension Scores</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; padding: 24px; line-height: 1.45; color: #1c1c1e; background: #fff; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: 13px; margin-bottom: 18px; }}
  .controls {{ position: sticky; top: 0; background: #fff; padding: 10px 0;
              border-bottom: 1px solid #e5e5e5; margin-bottom: 16px; z-index: 5; }}
  .qbtn {{ font-size: 13px; padding: 6px 12px; margin-right: 6px; border: 1px solid #ccc;
          border-radius: 6px; background: #f7f7f7; cursor: pointer; }}
  .qbtn.active {{ background: #1c1c1e; color: #fff; border-color: #1c1c1e; }}
  section.quarter {{ margin: 0 0 34px; }}
  h2 {{ font-size: 18px; margin: 10px 0 2px; }}
  .meta {{ color: #666; font-size: 12px; margin-bottom: 10px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #e2e2e2; padding: 8px 10px; vertical-align: top; text-align: left; }}
  th {{ background: #f2f2f4; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }}
  td.dim {{ font-weight: 600; width: 15%; white-space: nowrap; }}
  td.score, td.z {{ width: 8%; text-align: center; font-variant-numeric: tabular-nums;
                    font-weight: 600; }}
  td.z.na {{ color: #bbb; }}
  td.rationale {{ width: 69%; }}
  .rat {{ margin-bottom: 6px; }}
  ul.bul {{ margin: 0; padding-left: 18px; }}
  ul.bul li {{ margin: 2px 0; }}
  sup.ref a {{ text-decoration: none; color: #0a6; font-weight: 700; padding-left: 2px; }}
  .notes {{ margin-top: 12px; border-top: 1px dashed #ddd; padding-top: 8px; }}
  .notes h3 {{ font-size: 12px; text-transform: uppercase; color: #777; margin: 0 0 6px; }}
  .notes ol {{ margin: 0; padding-left: 22px; }}
  .notes li {{ font-size: 13px; color: #333; margin: 3px 0; }}
  .notes a.back {{ text-decoration: none; color: #0a6; font-weight: 700; margin-right: 4px; }}
  .canon {{ font-size: 12px; color: #555; margin: 2px 0 0 6px; padding-left: 8px;
           border-left: 2px solid #d8d8d8; }}
  .chip {{ font-size: 10px; text-transform: uppercase; letter-spacing: .03em;
          border-radius: 4px; padding: 1px 5px; margin-left: 6px; white-space: nowrap;
          vertical-align: middle; }}
  .chip.composite {{ color: #5a5a5a; background: #eef0f2; border: 1px solid #d7dbe0; }}
  .chip.anchored {{ color: #4a5a2e; background: #eef3e2; border: 1px solid #d3ddbf; }}
  .chip.paraphrased {{ color: #2e4a5a; background: #e2eef3; border: 1px solid #bfd3dd; }}
  .chip.unverified {{ color: #b00; background: #fdecec; border: 1px solid #f0c0c0; }}
  .legend {{ font-size: 11px; color: #777; margin-top: 8px; }}
  .legend .chip {{ margin-left: 0; margin-right: 4px; }}
  :target {{ background: rgba(255,220,0,.28); }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #1c1c1e; color: #ececec; }}
    .controls {{ background: #1c1c1e; border-color: #333; }}
    .qbtn {{ background: #2c2c2e; color: #ddd; border-color: #444; }}
    .qbtn.active {{ background: #ececec; color: #1c1c1e; }}
    th {{ background: #2c2c2e; }}
    th, td {{ border-color: #3a3a3c; }}
    .notes li {{ color: #ccc; }}
    .canon {{ color: #aaa; border-left-color: #444; }}
    .chip.composite {{ color: #cfd3d8; background: #34383d; border-color: #4a4f55; }}
    .chip.anchored {{ color: #cfe0b8; background: #313a28; border-color: #4c5a3a; }}
    .chip.paraphrased {{ color: #bcd8e6; background: #283740; border-color: #3a4f5a; }}
    .chip.unverified {{ color: #ff9b9b; background: #3a2626; border-color: #5a3a3a; }}
  }}
</style>
</head>
<body>
  <h1>{esc(company)} ({esc(ticker)}) &mdash; FY2024 Narrative Dimension Scores</h1>
  <div class="sub">LLM score is a -2.0 to +2.0 narrative-tone read from the earnings-call transcript (tenths encode intensity). Quant z is the standardized surprise/revision vs AMZN's own history. Compare direction and rank, not raw values. Model: {model} &middot; generated {generated}. See dimension_reference_key.txt for full methodology.</div>
  <div class="controls">{''.join(buttons)}
    <div class="legend">Evidence status:
      <span class="chip composite">composite</span>stitched (all fragments verbatim)
      <span class="chip anchored">anchored</span>verbatim span located for the claim
      <span class="chip paraphrased">paraphrased</span>faithful paraphrase (rescue-judge confirmed)
      <span class="chip unverified">unverified</span>no supporting span found
      &middot; plain quotes are exact verbatim matches.
    </div>
  </div>
  {''.join(sections)}
<script>
  (function () {{
    var btns = document.querySelectorAll('.qbtn');
    var secs = document.querySelectorAll('section.quarter');
    function show(target) {{
      secs.forEach(function (s) {{
        s.style.display = (target === 'ALL' || s.getAttribute('data-q') === target) ? '' : 'none';
      }});
      btns.forEach(function (b) {{
        b.classList.toggle('active', b.getAttribute('data-target') === target);
      }});
    }}
    btns.forEach(function (b) {{
      b.addEventListener('click', function () {{ show(b.getAttribute('data-target')); }});
    }});
    show('ALL');
  }})();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Build dimension HTML report.")
    ap.add_argument("--ticker", default="AMZN", help="Ticker symbol.")
    args = ap.parse_args()
    ticker = args.ticker.upper()
    view_file = resolve_read_required(ticker, "dimension_view", "json", layer="json")
    html_file = company_artifact(ticker, "reports", "dimension_report", "html", mkdir=True)

    view = json.loads(view_file.read_text(encoding="utf-8"))
    html_file.write_text(build_html(view), encoding="utf-8")
    n_q = len([
        q for q in view.get("quarters", [])
        if q.get("output_scope", False)
    ])
    print(f"Wrote {html_file}  ({n_q} quarters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
