#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-contained HTML report for Focus 3 narrative surprise scores.

    python "Structured Narrative/build_surprise_report.py"
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"
VIEW_FILE = OUT_DIR / "AMZN_surprise_view.json"
HTML_FILE = OUT_DIR / "AMZN_surprise_report.html"

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

DIR_LABELS = {
    "more_bullish_than_expected": "more bullish vs expected",
    "in_line": "in line",
    "more_bearish_than_expected": "more bearish vs expected",
}
DIR_ARROW = {
    "more_bullish_than_expected": "\u25B2",
    "in_line": "\u2013",
    "more_bearish_than_expected": "\u25BC",
}

STATUS_CHIPS = {
    "composite": ("composite", "Ellipsis-stitched quote — every fragment is verbatim."),
    "anchored": ("anchored", "Verbatim span located for the claim."),
    "paraphrased": ("paraphrased", "Faithful paraphrase confirmed by rescue judge."),
    "unverified": ("unverified", "No supporting span found."),
}


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


def mag_tint(v, hi: float = 2.0) -> str:
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


def fmt_gap(v) -> str:
    if v is None or not isinstance(v, (int, float)):
        return "&mdash;"
    return f"{float(v):+.2f}"


def agree_badge(agrees) -> str:
    if agrees is True:
        return '<span class="agree yes" title="Narrative surprise agrees with quant z direction.">quant agrees</span>'
    if agrees is False:
        return '<span class="agree no" title="Narrative surprise diverges from quant z — potential narrative surprise.">quant diverges</span>'
    return ""


def render_quarter(qi: int, q: dict, dim_order: list[str]) -> str:
    fp = q["fiscal_period"]
    by_dim = {d["dimension"]: d for d in q.get("surprises", [])}
    ordered = [by_dim[d] for d in dim_order if d in by_dim]
    ordered += [d for d in q.get("surprises", []) if d["dimension"] not in dim_order]

    note = 0
    rows_html: list[str] = []
    footnotes: list[str] = []

    for d in ordered:
        dim = d["dimension"]
        label = DIM_LABELS.get(dim, dim.replace("_", " ").title())
        direction = d.get("surprise_direction", "in_line")
        mag = d.get("surprise_magnitude")

        level_cell = f'<td class="level">{fmt_score(d.get("llm_level"))}</td>'
        if d.get("is_quant_comparable"):
            z_cell = f'<td class="z" style="{mag_tint(d.get("quant_z"), hi=1.5)}">{fmt_z(d.get("quant_z"))}</td>'
            gap_cell = f'<td class="gap" style="{mag_tint(d.get("narrative_quant_gap"), hi=2.0)}">{fmt_gap(d.get("narrative_quant_gap"))}</td>'
        else:
            z_cell = '<td class="z na">&mdash;</td>'
            gap_cell = '<td class="gap na">&mdash;</td>'

        arrow = DIR_ARROW.get(direction, "")
        surprise_cell = (
            f'<td class="surprise" style="{mag_tint(mag)}">'
            f'<span class="dir">{arrow} {esc(DIR_LABELS.get(direction, direction))}</span> '
            f'<span class="mag">{fmt_score(mag)}</span>'
            f'<div class="agreewrap">{agree_badge(d.get("agrees_with_quant"))}</div></td>'
        )

        bullets: list[str] = []
        for ev in d.get("evidence", []):
            note += 1
            src_id = f"src-{qi}-{note}"
            fn_id = f"fn-{qi}-{note}"
            sup = f'<sup class="ref" id="{src_id}"><a href="#{fn_id}">{note}</a></sup>'
            bullets.append(f"<li>{esc(ev.get('claim'))}{sup}</li>")
            status = status_of(ev)
            chip = status_chip(status)
            canon = ev.get("canonical")
            canon_html = ""
            if status in ("anchored", "paraphrased") and canon and canon.strip() != (ev.get("excerpt") or "").strip():
                canon_html = f'<div class="canon">verbatim: &ldquo;{esc(canon)}&rdquo;</div>'
            footnotes.append(
                f'<li id="{fn_id}"><a class="back" href="#{src_id}">[{note}]</a> '
                f'&ldquo;{esc(ev.get("excerpt"))}&rdquo;{chip}{canon_html}</li>'
            )

        rationale = f'<div class="rat">{esc(d.get("rationale"))}</div>' if d.get("rationale") else ""
        bullets_html = f"<ul class=\"bul\">{''.join(bullets)}</ul>" if bullets else ""
        rows_html.append(
            f"<tr><td class=\"dim\">{esc(label)}</td>{level_cell}{z_cell}{surprise_cell}{gap_cell}"
            f"<td class=\"rationale\">{rationale}{bullets_html}</td></tr>"
        )

    footnotes_html = (
        f'<div class="notes"><h3>Notes &mdash; narrative evidence</h3>'
        f'<ol>{"".join(footnotes)}</ol></div>'
        if footnotes else ""
    )
    meta = (
        f'as-of {esc(q.get("as_of_date") or "n/a")} '
        f'&middot; source: {esc(q.get("source"))} '
        f'&middot; {esc(q.get("n_chars"))} chars '
        f'&middot; excerpts supported: {esc(q.get("pct_verified"))}%'
    )

    return f"""
    <section class="quarter" data-q="{esc(fp)}">
      <h2>{esc(fp)}</h2>
      <div class="meta">{meta}</div>
      <table>
        <thead>
          <tr><th>Dimension</th><th>Level</th><th>Quant z</th><th>vs Consensus</th>
              <th>Gap</th><th>What diverged</th></tr>
        </thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
      {footnotes_html}
    </section>
    """


def build_html(view: dict) -> str:
    dim_order = view.get("dimension_order", list(DIM_LABELS.keys()))
    quarters = view.get("quarters", [])
    ticker = view.get("ticker", "")
    company = view.get("company_name", "")
    generated = esc(view.get("generated_at", ""))
    model = esc(view.get("model", ""))

    buttons = ['<button class="qbtn active" data-target="ALL">All</button>']
    sections: list[str] = []
    for qi, q in enumerate(quarters):
        fp = q["fiscal_period"]
        buttons.append(f'<button class="qbtn" data-target="{esc(fp)}">{esc(fp)}</button>')
        sections.append(render_quarter(qi, q, dim_order))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(ticker)} FY2024 Narrative Surprise</title>
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
  td.dim {{ font-weight: 600; width: 14%; white-space: nowrap; }}
  td.level, td.z, td.gap {{ width: 8%; text-align: center; font-variant-numeric: tabular-nums; font-weight: 600; }}
  td.z.na, td.gap.na {{ color: #bbb; font-weight: normal; }}
  td.surprise {{ width: 16%; font-variant-numeric: tabular-nums; }}
  td.surprise .dir {{ font-weight: 600; }}
  td.rationale {{ width: 46%; }}
  .agreewrap {{ margin-top: 3px; }}
  .agree {{ font-size: 10px; text-transform: uppercase; letter-spacing: .03em;
           border-radius: 4px; padding: 1px 5px; }}
  .agree.yes {{ color: #2e5a34; background: #e9f3ec; border: 1px solid #cfe3d4; }}
  .agree.no {{ color: #7a4a12; background: #fbf0df; border: 1px solid #eed6ab; }}
  .rat {{ margin-bottom: 6px; }}
  ul.bul {{ margin: 0; padding-left: 18px; }}
  sup.ref a {{ text-decoration: none; color: #0a6; font-weight: 700; }}
  .notes {{ margin-top: 12px; border-top: 1px dashed #ddd; padding-top: 8px; }}
  .notes h3 {{ font-size: 12px; text-transform: uppercase; color: #777; margin: 0 0 6px; }}
  .notes ol {{ margin: 0; padding-left: 22px; }}
  .notes a.back {{ text-decoration: none; color: #0a6; font-weight: 700; margin-right: 4px; }}
  .canon {{ font-size: 12px; color: #555; margin: 2px 0 0 6px; padding-left: 8px; border-left: 2px solid #d8d8d8; }}
  .chip {{ font-size: 10px; text-transform: uppercase; letter-spacing: .03em;
          border-radius: 4px; padding: 1px 5px; margin-left: 6px; }}
  .chip.unverified {{ color: #b00; background: #fdecec; border: 1px solid #f0c0c0; }}
  .legend {{ font-size: 11px; color: #777; margin-top: 8px; }}
  :target {{ background: rgba(255,220,0,.28); }}
</style>
</head>
<body>
  <h1>{esc(company)} ({esc(ticker)}) &mdash; FY2024 Narrative Surprise (Focus 3)</h1>
  <div class="sub">Compares management narrative to pre-call consensus. Level = Focus 1 tone; Quant z = standardized results surprise; vs Consensus = LLM narrative surprise; Gap = surprise magnitude minus quant z. Model: {model} &middot; generated {generated}. See surprise_reference_key.txt.</div>
  <div class="controls">{''.join(buttons)}
    <div class="legend">Gap &gt; 0 = management sounded more bullish than the quant surprise alone would suggest. &ldquo;quant diverges&rdquo; = opposite signs on surprise magnitude and quant z.</div>
  </div>
  {''.join(sections)}
<script>
(function () {{
  var btns = document.querySelectorAll('.qbtn');
  var secs = document.querySelectorAll('section.quarter');
  function show(t) {{
    secs.forEach(function (s) {{ s.style.display = (t === 'ALL' || s.getAttribute('data-q') === t) ? '' : 'none'; }});
    btns.forEach(function (b) {{ b.classList.toggle('active', b.getAttribute('data-target') === t); }});
  }}
  btns.forEach(function (b) {{ b.addEventListener('click', function () {{ show(b.getAttribute('data-target')); }}); }});
  show('ALL');
}})();
</script>
</body>
</html>
"""


def main() -> int:
    if not VIEW_FILE.exists():
        print(f"Missing {VIEW_FILE}. Run run_surprise_scoring.py first.", file=sys.stderr)
        return 1
    view = json.loads(VIEW_FILE.read_text(encoding="utf-8"))
    HTML_FILE.write_text(build_html(view), encoding="utf-8")
    print(f"Wrote {HTML_FILE}  ({len(view.get('quarters', []))} quarters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
