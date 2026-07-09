#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Render a shareable, z-score-framed PDF of Amazon's narrative-quant features
across full history, from the analysis-layer output
(AMZN_dimension_scores.* and AMZN_narrative_zscored.*).

The framing is deliberately comparative: every value is expressed in standard
deviations versus AMZN's own history (0 = AMZN-typical, +1.5 = unusually strong
for AMZN), which is the "easily understandable when sharing" view.

Sections:
  1. Dimension-score heatmap across every quarter (full-sample z).
  2. Measure-level surprise heatmap (drill-down).
  3. Latest-quarter dimension bars with a plain-language legend.
  4. Latest-quarter evidence table (measure z-scores + provenance).

Usage:  python "Structured Narrative/make_zscore_report.py"
Output: Structured Narrative/output/AMZN/reports/zscore_report.pdf
"""
import os
import sys

import pandas as pd

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
from output_paths import company_artifact, resolve_read_required  # noqa: E402

TICKER = "AMZN"
DIM_PARQUET = str(resolve_read_required(TICKER, "dimension_scores", "parquet", layer="parquet"))
LONG_PARQUET = str(resolve_read_required(TICKER, "narrative_zscored", "parquet", layer="parquet"))
PDF = str(company_artifact(TICKER, "reports", "zscore_report", "pdf", mkdir=True))

# Dimension display order + friendly labels.
DIM_ORDER = [
    ("dim_demand_z", "Demand / Growth"),
    ("dim_margins_z", "Margins / Profitability"),
    ("dim_earnings_power_z", "Earnings power (EPS)"),
    ("dim_capital_allocation_z", "Capital allocation / Cash"),
    ("dim_guidance_z", "Guidance (fwd revisions)"),
]
MEASURE_ORDER = [20, 431, 418, 373, 6, 8, 27, 9, 237, 22, 213]

INK   = colors.HexColor(0x1F2937)
MUTED = colors.HexColor(0x6B7280)
LINE  = colors.HexColor(0xE5E7EB)
ACCENT = colors.HexColor(0x1D4ED8)
GREEN = colors.HexColor(0x1A7F37)
RED   = colors.HexColor(0xB42318)
NA    = colors.HexColor(0xF0F1F3)
Z_CAP = 2.5   # saturation point for the color scale


def zcolor(z):
    """Diverging color: white at 0, green for positive, red for negative."""
    if z is None or pd.isna(z):
        return NA
    z = max(-Z_CAP, min(Z_CAP, float(z)))
    t = abs(z) / Z_CAP
    tr, tg, tb = (26, 127, 55) if z >= 0 else (180, 35, 24)
    r = 255 + t * (tr - 255)
    g = 255 + t * (tg - 255)
    b = 255 + t * (tb - 255)
    return colors.Color(r / 255.0, g / 255.0, b / 255.0)


def qtag(period: str) -> str:
    """FY2025-Q2 -> '25Q2 ; year shown only at Q1 to keep the axis readable."""
    yr = period[2:6][-2:]
    q = period[-2:]
    return f"'{yr}" if q == "Q1" else q


def heatmap(df, row_specs, value_fn, styles, usable_w):
    """row_specs: list of (key, label). value_fn(row_key, period) -> z or None."""
    periods = df["fiscal_period"].tolist()
    label_w = 1.55 * inch
    cell_w = (usable_w - label_w) / len(periods)

    header = [""] + [qtag(p) for p in periods]
    grid = [header]
    for key, label in row_specs:
        grid.append([label] + ["" for _ in periods])

    t = Table(grid, colWidths=[label_w] + [cell_w] * len(periods),
              rowHeights=[0.20 * inch] + [0.30 * inch] * len(row_specs))
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 5),
        ("FONTSIZE", (0, 1), (0, -1), 7),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica"),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (1, 0), (-1, -1), 0),
        ("RIGHTPADDING", (1, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (0, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("GRID", (1, 1), (-1, -1), 0.25, colors.white),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, LINE),
    ]
    for ri, (key, _label) in enumerate(row_specs, start=1):
        for ci, p in enumerate(periods, start=1):
            style.append(("BACKGROUND", (ci, ri), (ci, ri),
                          zcolor(value_fn(key, p))))
    t.setStyle(TableStyle(style))
    return t


def colorbar(styles):
    steps = [-2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    row = [Paragraph("Scale (&sigma; vs AMZN history):", styles["nq_src"])]
    cells = [row[0]] + ["" for _ in steps]
    t = Table([[""] * 1 + [f"{s:+.1f}" if s else "0" for s in steps]],
              colWidths=[1.7 * inch] + [0.5 * inch] * len(steps),
              rowHeights=[0.22 * inch])
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("SPAN", (0, 0), (0, 0)),
        ("TEXTCOLOR", (0, 0), (0, 0), MUTED),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
    ]
    for ci, s in enumerate(steps, start=1):
        style.append(("BACKGROUND", (ci, 0), (ci, 0), zcolor(s)))
    t.setStyle(TableStyle(style))
    return t


def dim_bar(dim_df, styles):
    latest = dim_df.iloc[-1]
    labels = [lbl for _, lbl in DIM_ORDER]
    vals = [round(float(latest[k]), 2) if pd.notna(latest[k]) else 0.0
            for k, _ in DIM_ORDER]

    d = Drawing(520, 220)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 30, 70, 470, 130
    bc.data = [vals]
    bc.categoryAxis.categoryNames = ["Demand", "Margins", "EPS", "Capital", "Guidance"]
    bc.categoryAxis.labels.fontSize = 7
    bc.valueAxis.valueMin = min(-2.5, min(vals) - 0.3)
    bc.valueAxis.valueMax = max(2.5, max(vals) + 0.3)
    bc.valueAxis.valueStep = 0.5
    bc.barWidth = 14
    bc.groupSpacing = 18
    bc.barLabelFormat = "%0.2f"
    bc.barLabels.fontSize = 7
    bc.barLabels.dy = 3
    for i, v in enumerate(vals):
        bc.bars[(0, i)].fillColor = GREEN if v >= 0 else RED
    d.add(bc)
    return d, latest


def evidence_table(long_df, latest_period, styles):
    rq = long_df[(long_df["period_role"] == "reported_q") &
                 (long_df["fiscal_period"] == latest_period)]
    by = {int(r["measure"]): r for _, r in rq.iterrows()}

    headers = ["Measure", "Actual", "Consensus", "Surprise %",
               "Surprise z", "z (PIT)", "Analysts", "As-of"]
    rows = [headers]
    tone = []
    for code in MEASURE_ORDER:
        r = by.get(code)
        if r is None:
            continue
        sp = r["earnings_surprise_pct"]
        z = r["earnings_surprise_pct_z"]
        zp = r["earnings_surprise_pct_z_pit"]
        asof = r["consensus_pre_effectivedate"]
        rows.append([
            str(r["measure_label"]),
            "-" if pd.isna(r["actual_value"]) else f"{r['actual_value']:,.2f}",
            "-" if pd.isna(r["consensus_pre_mean"]) else f"{r['consensus_pre_mean']:,.2f}",
            "-" if pd.isna(sp) else f"{sp * 100:+.1f}%",
            "-" if pd.isna(z) else f"{z:+.2f}",
            "-" if pd.isna(zp) else f"{zp:+.2f}",
            "-" if pd.isna(r["consensus_pre_numests"]) else str(int(r["consensus_pre_numests"])),
            "-" if pd.isna(asof) else pd.to_datetime(asof).strftime("%Y-%m-%d"),
        ])
        if pd.notna(z):
            tone.append((len(rows) - 1, GREEN if z >= 0 else RED))

    col_w = [1.7 * inch, 1.0 * inch, 1.0 * inch, 0.9 * inch,
             0.8 * inch, 0.8 * inch, 0.7 * inch, 1.0 * inch]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(0x111827)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, LINE),
    ]
    for r_idx in range(1, len(rows)):
        if r_idx % 2 == 0:
            style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor(0xF7F8FA)))
    for r_idx, col in tone:
        style.append(("TEXTCOLOR", (4, r_idx), (5, r_idx), col))
        style.append(("FONTNAME", (4, r_idx), (4, r_idx), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    return t


def build():
    dim = pd.read_parquet(DIM_PARQUET)
    long_df = pd.read_parquet(LONG_PARQUET)
    dim = dim.sort_values("earnings_datetime").reset_index(drop=True)

    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("nq_title", parent=ss["Title"], fontSize=16, leading=20,
                          textColor=INK, spaceAfter=2))
    ss.add(ParagraphStyle("nq_cap", parent=ss["Normal"], fontSize=9.5, leading=13,
                          textColor=INK, spaceAfter=2))
    ss.add(ParagraphStyle("nq_src", parent=ss["Normal"], fontSize=7.5, leading=10,
                          textColor=MUTED, spaceAfter=6))
    ss.add(ParagraphStyle("nq_h2", parent=ss["Normal"], fontSize=12, leading=15,
                          textColor=INK, fontName="Helvetica-Bold",
                          spaceBefore=6, spaceAfter=4))
    ss.add(ParagraphStyle("nq_call", parent=ss["Normal"], fontSize=9, leading=13,
                          textColor=INK))

    page = landscape(letter)
    usable_w = page[0] - 1.0 * inch
    doc = SimpleDocTemplate(PDF, pagesize=page,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch,
                            title="Amazon Narrative-Quant Z-Scores")

    first = dim["fiscal_period"].iloc[0]
    last = dim["fiscal_period"].iloc[-1]
    story = []
    story.append(Paragraph(
        "Amazon &mdash; Earnings-Call Narrative-Quant, Standardized (z-scores)", ss["nq_title"]))
    story.append(Paragraph(
        f"Every measure and dimension is expressed in standard deviations versus AMZN&rsquo;s own "
        f"history ({first} &ndash; {last}). 0 = AMZN-typical; +1.5 = unusually strong for AMZN; "
        f"&minus;1.5 = unusually weak. This removes AMZN&rsquo;s structural beat bias so quarters "
        f"are comparable.", ss["nq_cap"]))
    story.append(Paragraph(
        "Colors use full-sample z (descriptive). A look-ahead-safe point-in-time z "
        "(*_z_pit, prior-quarters-only) is also written to the data files and reserved for the "
        "alpha / XGBoost stage. Source: LSEG VW_IBES2SUMPER / TREACTRPT; MSCI EFMUSALTS.",
        ss["nq_src"]))
    story.append(colorbar(ss))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Dimension scores across history (&sigma; vs AMZN)", ss["nq_h2"]))
    dim_vals = {(k, p): dim.loc[dim["fiscal_period"] == p, k].iloc[0]
                for k, _ in DIM_ORDER for p in dim["fiscal_period"]}
    story.append(heatmap(dim, DIM_ORDER,
                         lambda k, p: dim_vals.get((k, p)), ss, usable_w))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Measure-level surprise (drill-down, &sigma; vs AMZN)", ss["nq_h2"]))
    rq = long_df[long_df["period_role"] == "reported_q"]
    m_lookup = {(int(r["measure"]), r["fiscal_period"]): r["earnings_surprise_pct_z"]
                for _, r in rq.iterrows()}
    m_labels = {int(r["measure"]): r["measure_label"] for _, r in rq.iterrows()}
    m_specs = [(c, m_labels.get(c, str(c))) for c in MEASURE_ORDER if c in m_labels]
    story.append(heatmap(dim, m_specs,
                         lambda k, p: m_lookup.get((k, p)), ss, usable_w))
    story.append(Spacer(1, 14))

    bar, latest = dim_bar(dim, ss)
    block = [
        Paragraph(f"Latest quarter: {last} (reported {latest['earnings_date']})", ss["nq_h2"]),
        Paragraph(
            "How this quarter&rsquo;s print compared to AMZN&rsquo;s own history, by dimension. "
            "Bars are standard deviations: near 0 is a typical AMZN quarter, positive is an "
            "unusually strong surprise/revision for AMZN, negative unusually weak. Sign is raw "
            "(e.g. higher capex reads positive); directional interpretation is deferred to the "
            "LLM dimension layer.", ss["nq_call"]),
        Spacer(1, 4), bar, Spacer(1, 8),
        Paragraph("Latest-quarter evidence (measure z-scores + provenance)", ss["nq_h2"]),
        evidence_table(long_df, last, ss),
    ]
    story.append(KeepTogether(block))

    doc.build(story)
    print("Wrote", PDF)


if __name__ == "__main__":
    build()
