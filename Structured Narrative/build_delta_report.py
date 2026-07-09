#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-contained HTML report for the AMZN quarter-over-quarter narrative deltas.
==============================================================================

Reads output/AMZN_delta_view.json (from run_delta_scoring.py) and writes a single
dependency-free output/AMZN_delta_report.html.

Features:
  * Filter by transition (buttons: each "Qn-1 -> Qn" + "All").
  * A table per transition: Dimension | Level (prior -> current) | delta score |
    Change (direction + magnitude, tinted) | Quant delta-z | What changed.
  * "What changed" is bullet-pointed; each bullet carries a superscript note that
    links to the current-quarter excerpt in a per-transition Notes section, with
    the same evidence-status chips as the level report.

    python "Structured Narrative/build_delta_report.py"
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

STATUS_CHIPS = {
    "composite": ("composite", "Ellipsis-stitched quote — every fragment is verbatim in the transcript."),
    "anchored": ("anchored", "A supporting contiguous verbatim span was located in the transcript for this claim."),
    "paraphrased": ("paraphrased", "Faithful paraphrase/shortening — the rescue judge confirmed support and returned a verbatim quote."),
    "unverified": ("unverified", "No supporting span could be found in the transcript."),
}

DIR_LABELS = {
    "improved": "improved",
    "steady": "steady",
    "deteriorated": "deteriorated",
}
DIR_ARROW = {"improved": "\u25B2", "steady": "\u2013", "deteriorated": "\u25BC"}


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def status_of(ev: dict) -> str:
    status = ev.get("status")
    if status:
        return status
    return "verbatim" if ev.get("verified") else "unverified"


def status_chip(status: str) -> str:
    if status not in STATUS_CHIPS:
        return ""
    label, title = STATUS_CHIPS[status]
    return f' <span class="chip {esc(status)}" title="{esc(title)}">{esc(label)}</span>'


def mag_tint(v: float | None, hi: float = 2.0) -> str:
    """Green for improvement (+), red for deterioration (-), scaled by magnitude."""
    if v is None:
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
    if v is None or not isinstance(v, (int, float)):
        return "&mdash;"
    return f"{float(v):+.1f}"


def fmt_z(v) -> str:
    if v is None or not isinstance(v, (int, float)):
        return "&mdash;"
    return f"{float(v):+.2f}"


def agree_badge(agrees) -> str:
    if agrees is True:
        return '<span class="agree yes" title="Narrative change agrees in direction with the numbers.">numbers agree</span>'
    if agrees is False:
        return '<span class="agree no" title="Narrative change diverges from the numbers — potential narrative surprise.">numbers diverge</span>'
    return ""


def render_transition(ti: int, t: dict, dim_order: list[str]) -> str:
    prior = t.get("prior_period", "")
    current = t.get("fiscal_period", "")
    key = f"{prior}->{current}"
    by_dim = {d["dimension"]: d for d in t.get("deltas", [])}
    ordered = [by_dim[d] for d in dim_order if d in by_dim]
    ordered += [d for d in t.get("deltas", []) if d["dimension"] not in dim_order]

    note = 0
    rows_html: list[str] = []
    footnotes: list[str] = []

    for d in ordered:
        dim = d["dimension"]
        label = DIM_LABELS.get(dim, dim.replace("_", " ").title())
        direction = d.get("change_direction", "steady")
        mag = d.get("change_magnitude")

        level_cell = (
            f'<td class="level">{fmt_score(d.get("prior_score"))} '
            f'&rarr; {fmt_score(d.get("current_score"))}</td>'
        )
        delta_cell = (
            f'<td class="score" style="{mag_tint(d.get("score_delta"))}">'
            f'{fmt_score(d.get("score_delta"))}</td>'
        )
        arrow = DIR_ARROW.get(direction, "")
        change_cell = (
            f'<td class="change" style="{mag_tint(mag)}">'
            f'<span class="dir">{arrow} {esc(DIR_LABELS.get(direction, direction))}</span> '
            f'<span class="mag">{fmt_score(mag)}</span>'
            f'<div class="agreewrap">{agree_badge(d.get("agrees_with_numbers"))}</div></td>'
        )
        if d.get("is_quant_comparable"):
            zc = d.get("quant_z_delta")
            z_cell = f'<td class="z" style="{mag_tint(zc, hi=1.5)}">{fmt_z(zc)}</td>'
        else:
            z_cell = '<td class="z na">&mdash;</td>'

        bullets: list[str] = []
        for ev in d.get("evidence", []):
            note += 1
            src_id = f"src-{ti}-{note}"
            fn_id = f"fn-{ti}-{note}"
            sup = (
                f'<sup class="ref" id="{src_id}"><a href="#{fn_id}">{note}</a></sup>'
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
                canon_html = f'<div class="canon">verbatim: &ldquo;{esc(canon)}&rdquo;</div>'
            footnotes.append(
                f'<li id="{fn_id}">'
                f'<a class="back" href="#{src_id}">[{note}]</a> '
                f'&ldquo;{esc(ev.get("excerpt"))}&rdquo;{chip}{canon_html}</li>'
            )

        rationale = f'<div class="rat">{esc(d.get("rationale"))}</div>' if d.get("rationale") else ""
        bullets_html = f"<ul class=\"bul\">{''.join(bullets)}</ul>" if bullets else ""
        rows_html.append(
            f'<tr><td class="dim">{esc(label)}</td>{level_cell}{delta_cell}'
            f'{change_cell}{z_cell}'
            f'<td class="rationale">{rationale}{bullets_html}</td></tr>'
        )

    footnotes_html = (
        f'<div class="notes"><h3>Notes &mdash; current-quarter change evidence</h3>'
        f'<ol>{"".join(footnotes)}</ol></div>'
        if footnotes else ""
    )
    meta = (
        f'{esc(prior)} &rarr; {esc(current)} '
        f'&middot; as-of {esc(t.get("as_of_date") or "n/a")} '
        f'&middot; source: {esc(t.get("source"))} '
    )
    if t.get("delta_context") == "both_transcripts":
        meta += (
            f'&middot; prior {esc(t.get("n_chars_prior"))} chars '
            f'&middot; current {esc(t.get("n_chars_current"))} chars '
        )
    elif t.get("n_chars_current") or t.get("n_chars"):
        meta += f'&middot; {esc(t.get("n_chars_current") or t.get("n_chars"))} chars '
    meta += f'&middot; change-excerpts supported: {esc(t.get("pct_verified"))}%'

    return f"""
    <section class="transition" data-t="{esc(key)}">
      <h2>{esc(prior)} &rarr; {esc(current)}</h2>
      <div class="meta">{meta}</div>
      <table>
        <thead>
          <tr><th>Dimension</th><th>Level (prior &rarr; current)</th><th>&Delta; score</th>
              <th>Change</th><th>Quant &Delta;z</th><th>What changed</th></tr>
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
    transitions = view.get("transitions", [])
    ticker = view.get("ticker", "")
    company = view.get("company_name", "")

    buttons = ['<button class="tbtn active" data-target="ALL">All</button>']
    sections: list[str] = []
    for ti, t in enumerate(transitions):
        key = f"{t.get('prior_period','')}->{t.get('fiscal_period','')}"
        lbl = f"{t.get('prior_period','')} \u2192 {t.get('fiscal_period','')}"
        buttons.append(f'<button class="tbtn" data-target="{esc(key)}">{esc(lbl)}</button>')
        sections.append(render_transition(ti, t, dim_order))

    generated = esc(view.get("generated_at", ""))
    model = esc(view.get("model", ""))
    ctx = view.get("delta_context", "summary")
    ctx_label = (
        "both full transcripts (prior + current)"
        if ctx == "both_transcripts"
        else "prior summary + current transcript"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(ticker)} FY2024 Narrative Delta (QoQ change)</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; padding: 24px; line-height: 1.45; color: #1c1c1e; background: #fff; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: 13px; margin-bottom: 18px; }}
  .controls {{ position: sticky; top: 0; background: #fff; padding: 10px 0;
              border-bottom: 1px solid #e5e5e5; margin-bottom: 16px; z-index: 5; }}
  .tbtn {{ font-size: 13px; padding: 6px 12px; margin-right: 6px; border: 1px solid #ccc;
          border-radius: 6px; background: #f7f7f7; cursor: pointer; }}
  .tbtn.active {{ background: #1c1c1e; color: #fff; border-color: #1c1c1e; }}
  section.transition {{ margin: 0 0 34px; }}
  h2 {{ font-size: 18px; margin: 10px 0 2px; }}
  .meta {{ color: #666; font-size: 12px; margin-bottom: 10px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #e2e2e2; padding: 8px 10px; vertical-align: top; text-align: left; }}
  th {{ background: #f2f2f4; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }}
  td.dim {{ font-weight: 600; width: 13%; white-space: nowrap; }}
  td.level {{ width: 11%; text-align: center; font-variant-numeric: tabular-nums; color: #555; white-space: nowrap; }}
  td.score, td.z {{ width: 7%; text-align: center; font-variant-numeric: tabular-nums; font-weight: 600; }}
  td.z.na {{ color: #bbb; }}
  td.change {{ width: 14%; font-variant-numeric: tabular-nums; }}
  td.change .dir {{ font-weight: 600; }}
  td.change .mag {{ color: #444; }}
  td.rationale {{ width: 48%; }}
  .agreewrap {{ margin-top: 3px; }}
  .agree {{ font-size: 10px; text-transform: uppercase; letter-spacing: .03em;
           border-radius: 4px; padding: 1px 5px; }}
  .agree.yes {{ color: #2e5a34; background: #e9f3ec; border: 1px solid #cfe3d4; }}
  .agree.no {{ color: #7a4a12; background: #fbf0df; border: 1px solid #eed6ab; }}
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
          border-radius: 4px; padding: 1px 5px; margin-left: 6px; white-space: nowrap; vertical-align: middle; }}
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
    .tbtn {{ background: #2c2c2e; color: #ddd; border-color: #444; }}
    .tbtn.active {{ background: #ececec; color: #1c1c1e; }}
    th {{ background: #2c2c2e; }}
    th, td {{ border-color: #3a3a3c; }}
    td.level {{ color: #aaa; }}
    .notes li {{ color: #ccc; }}
    .canon {{ color: #aaa; border-left-color: #444; }}
    .agree.yes {{ color: #bfe4c6; background: #26331f; border-color: #3a4f2e; }}
    .agree.no {{ color: #e6c58a; background: #3a2f1c; border-color: #5a4a2e; }}
    .chip.composite {{ color: #cfd3d8; background: #34383d; border-color: #4a4f55; }}
    .chip.anchored {{ color: #cfe0b8; background: #313a28; border-color: #4c5a3a; }}
    .chip.paraphrased {{ color: #bcd8e6; background: #283740; border-color: #3a4f5a; }}
    .chip.unverified {{ color: #ff9b9b; background: #3a2626; border-color: #5a3a3a; }}
  }}
</style>
</head>
<body>
  <h1>{esc(company)} ({esc(ticker)}) &mdash; FY2024 Narrative Delta (quarter-over-quarter change)</h1>
  <div class="sub">Each row is how a dimension's narrative CHANGED vs the prior quarter. Change = LLM read of the shift (direction + magnitude on -2.0..+2.0); &Delta; score is the raw level difference; Quant &Delta;z is the change in the standardized surprise. Context: {esc(ctx_label)}. "numbers agree/diverge" flags whether the narrative change lines up with the level delta. Model: {model} &middot; generated {generated}. See delta_reference_key.txt for full methodology.</div>
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
    var btns = document.querySelectorAll('.tbtn');
    var secs = document.querySelectorAll('section.transition');
    function show(target) {{
      secs.forEach(function (s) {{
        s.style.display = (target === 'ALL' || s.getAttribute('data-t') === target) ? '' : 'none';
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
    ap = argparse.ArgumentParser(description="Build delta HTML report.")
    ap.add_argument("--ticker", default="AMZN", help="Ticker symbol.")
    args = ap.parse_args()
    ticker = args.ticker.upper()
    view_file = resolve_read_required(ticker, "delta_view", "json", layer="json")
    html_file = company_artifact(ticker, "reports", "delta_report", "html", mkdir=True)

    view = json.loads(view_file.read_text(encoding="utf-8"))
    html_file.write_text(build_html(view), encoding="utf-8")
    n_t = len(view.get("transitions", []))
    print(f"Wrote {html_file}  ({n_t} transitions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
