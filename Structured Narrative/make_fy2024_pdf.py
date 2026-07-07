#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Render a print-friendly PDF report of Amazon's FY2024 narrative-quant features
directly from the extractor output (AMZN_narrative_quant.csv). This mirrors the
Cursor canvas but as a portable, shareable PDF.

Usage:  python "Structured Narrative/make_fy2024_pdf.py"
Output: Structured Narrative/output/AMZN_FY2024_report.pdf
"""
import os
import pandas as pd

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.textlabels import Label

BASE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(BASE, "output", "AMZN_narrative_quant.csv")
PDF = os.path.join(BASE, "output", "AMZN_FY2024_report.pdf")

QUARTERS = ["FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4"]
MEASURE_ORDER = [20, 6, 8, 27, 9, 237, 22, 213, 418, 431, 373]
MONEY = {20, 6, 8, 237, 22, 213, 418, 431, 373}
EPS = {9}
PCT = {27}

INK    = colors.HexColor(0x1F2937)
MUTED  = colors.HexColor(0x6B7280)
GREEN  = colors.HexColor(0x1A7F37)
RED    = colors.HexColor(0xB42318)
HEADBG = colors.HexColor(0x111827)
STRIPE = colors.HexColor(0xF7F8FA)
LINE   = colors.HexColor(0xE5E7EB)
CALLBG = colors.HexColor(0xEFF4FB)
ACCENT = colors.HexColor(0x1D4ED8)


def sgn(v):
    return "+" if v >= 0 else "-"


def fmt_level(code, v):
    if v is None or pd.isna(v):
        return "-"
    if code in EPS:
        return "$%.2f" % v
    if code in PCT:
        return "%.2f%%" % v
    return "{:,.0f}".format(v)


def fmt_surprise(code, v):
    if v is None or pd.isna(v):
        return "-"
    a = abs(v)
    if code in EPS:
        return "%s$%.2f" % (sgn(v), a)
    if code in PCT:
        return "%s%.2f pp" % (sgn(v), a)
    return "%s%s" % (sgn(v), "{:,.0f}".format(a))


def fmt_pct(code, v):
    if code in PCT or v is None or pd.isna(v):
        return "-"
    return "%s%.2f%%" % (sgn(v), abs(v) * 100.0)


def load():
    df = pd.read_csv(CSV)
    rq = df[(df["period_role"] == "reported_q") & (df["fiscal_period"].isin(QUARTERS))]
    per_q = {}
    for qkey in QUARTERS:
        sub = rq[rq["fiscal_period"] == qkey]
        if sub.empty:
            continue
        row0 = sub.iloc[0]
        per_q[qkey] = {
            "earnings_date": str(row0["earnings_date"]),
            "alpha90": float(row0["alpha_spec_0_90"]) if pd.notna(row0["alpha_spec_0_90"]) else None,
            "by_measure": {int(r["measure"]): r for _, r in sub.iterrows()},
        }
    return per_q


def summary_stats(per_q):
    eps_sp, rev_sp = [], []
    eps_beats = fcf_below = 0
    for qkey in QUARTERS:
        q = per_q.get(qkey)
        if not q:
            continue
        eps = q["by_measure"].get(9)
        sal = q["by_measure"].get(20)
        fcf = q["by_measure"].get(237)
        if eps is not None and pd.notna(eps["earnings_surprise_pct"]):
            eps_sp.append(eps["earnings_surprise_pct"] * 100)
            if eps["earnings_surprise"] > 0:
                eps_beats += 1
        if sal is not None and pd.notna(sal["earnings_surprise_pct"]):
            rev_sp.append(sal["earnings_surprise_pct"] * 100)
        if fcf is not None and pd.notna(fcf["earnings_surprise"]) and fcf["earnings_surprise"] < 0:
            fcf_below += 1
    n = len([k for k in QUARTERS if k in per_q])
    return {
        "eps_avg": sum(eps_sp) / len(eps_sp) if eps_sp else 0,
        "eps_beats": f"{eps_beats} / {n}",
        "rev_avg": sum(rev_sp) / len(rev_sp) if rev_sp else 0,
        "fcf_below": f"{fcf_below} / {n}",
    }


def surprise_chart(per_q):
    labels = {20: "Revenue", 6: "EBIT (op. income)", 9: "EPS"}
    series_codes = [20, 6, 9]
    cats = [q.replace("FY2024-", "") for q in QUARTERS if q in per_q]
    data = []
    for code in series_codes:
        row = []
        for qkey in QUARTERS:
            q = per_q.get(qkey)
            m = q["by_measure"].get(code) if q else None
            row.append(round(m["earnings_surprise_pct"] * 100, 2)
                       if m is not None and pd.notna(m["earnings_surprise_pct"]) else 0)
        data.append(row)

    d = Drawing(500, 240)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 40, 30, 380, 180
    bc.data = data
    bc.categoryAxis.categoryNames = cats
    bc.valueAxis.valueMin = -10
    bc.valueAxis.valueMax = 45
    bc.valueAxis.valueStep = 10
    bc.valueAxis.labelTextFormat = "%d%%"
    bc.barSpacing = 1
    bc.groupSpacing = 14
    bc.bars[0].fillColor = colors.HexColor(0x94A3B8)
    bc.bars[1].fillColor = colors.HexColor(0x4B9CD3)
    bc.bars[2].fillColor = ACCENT
    bc.barLabelFormat = "%0.1f"
    bc.barLabels.fontSize = 6
    bc.barLabels.dy = 4
    d.add(bc)

    legend = Legend()
    legend.x, legend.y = 430, 190
    legend.dx = legend.dy = 6
    legend.fontSize = 7
    legend.alignment = "right"
    legend.colorNamePairs = [
        (colors.HexColor(0x94A3B8), labels[20]),
        (colors.HexColor(0x4B9CD3), labels[6]),
        (ACCENT, labels[9]),
    ]
    d.add(legend)
    return d


def quarter_table(qkey, q, styles):
    headers = ["Measure", "Actual", "Consensus", "Surprise", "Surprise %", "Analysts"]
    rows = [headers]
    tone = []  # (row_idx, color) for surprise columns
    for i, code in enumerate(MEASURE_ORDER, start=1):
        r = q["by_measure"].get(code)
        if r is None:
            continue
        s = r["earnings_surprise"]
        rows.append([
            str(r["measure_label"]),
            fmt_level(code, r["actual_value"]),
            fmt_level(code, r["consensus_pre_mean"]),
            fmt_surprise(code, s),
            fmt_pct(code, r["earnings_surprise_pct"]),
            "-" if pd.isna(r["consensus_pre_numests"]) else str(int(r["consensus_pre_numests"])),
        ])
        if pd.notna(s):
            tone.append((len(rows) - 1, GREEN if s > 0 else RED))

    col_w = [1.55 * inch, 1.0 * inch, 1.0 * inch, 0.95 * inch, 0.85 * inch, 0.75 * inch]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADBG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, LINE),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
    ]
    for r_idx in range(1, len(rows)):
        if r_idx % 2 == 0:
            style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), STRIPE))
    for r_idx, col in tone:
        style.append(("TEXTCOLOR", (3, r_idx), (4, r_idx), col))
        style.append(("FONTNAME", (3, r_idx), (3, r_idx), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))

    alpha = q["alpha90"]
    alpha_str = "n/a" if alpha is None else ("%s%.2f%%" % ("+" if alpha >= 0 else "", alpha * 100))
    hdr = Paragraph(
        f"<b>{qkey}</b>&nbsp;&nbsp;·&nbsp;&nbsp;reported {q['earnings_date']}"
        f"&nbsp;&nbsp;·&nbsp;&nbsp;forward-90d specific return {alpha_str}",
        styles["nq_qhead"],
    )
    return KeepTogether([hdr, Spacer(1, 4), t, Spacer(1, 14)])


def stat_strip(stats, styles):
    def cell(value, label, color):
        return [
            Paragraph(value, ParagraphStyle("v", parent=styles["Normal"], fontSize=17,
                                            leading=20, textColor=color,
                                            fontName="Helvetica-Bold")),
            Paragraph(label, ParagraphStyle("l", parent=styles["Normal"], fontSize=8,
                                            textColor=MUTED)),
        ]
    data = [[
        cell("%+.1f%%" % stats["eps_avg"], "Avg EPS surprise", GREEN),
        cell(stats["eps_beats"], "Quarters EPS beat", GREEN),
        cell("%+.1f%%" % stats["rev_avg"], "Avg revenue surprise", INK),
        cell(stats["fcf_below"], "Quarters FCF below consensus", RED),
    ]]
    t = Table(data, colWidths=[1.5 * inch] * 4)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def build():
    per_q = load()
    if not per_q:
        raise SystemExit("No FY2024 rows found in CSV.")
    stats = summary_stats(per_q)

    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("nq_title", parent=ss["Title"], fontSize=17, leading=21,
                          textColor=INK, spaceAfter=2))
    ss.add(ParagraphStyle("nq_cap", parent=ss["Normal"], fontSize=9.5, leading=13,
                          textColor=INK, spaceAfter=2))
    ss.add(ParagraphStyle("nq_src", parent=ss["Normal"], fontSize=7.5, leading=10,
                          textColor=MUTED, spaceAfter=6))
    ss.add(ParagraphStyle("nq_h2", parent=ss["Normal"], fontSize=12, leading=15,
                          textColor=INK, fontName="Helvetica-Bold",
                          spaceBefore=6, spaceAfter=4))
    ss.add(ParagraphStyle("nq_qhead", parent=ss["Normal"], fontSize=10, leading=13,
                          textColor=INK, spaceAfter=0))
    ss.add(ParagraphStyle("nq_call", parent=ss["Normal"], fontSize=9, leading=13,
                          textColor=INK))

    doc = SimpleDocTemplate(PDF, pagesize=letter,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.55 * inch, bottomMargin=0.55 * inch,
                            title="Amazon FY2024 Narrative-Quant Features")
    story = []
    story.append(Paragraph("Amazon FY2024 &mdash; Earnings-Call Narrative-Quant Features", ss["nq_title"]))
    story.append(Paragraph(
        "Point-in-time actual vs. pre-announcement consensus for each measure, with a "
        "forward MSCI specific-return label. Every value carries its analyst count and the "
        "effective date the consensus was live &mdash; the quantitative spine the LLM narrative "
        "scores attach to.", ss["nq_cap"]))
    story.append(Paragraph(
        "Source: LSEG VW_IBES2SUMPER (consensus) &middot; TREACTRPT (actuals) &middot; "
        "MSCI ASSET_SPECIFIC_RETURN_TS EFMUSALTS (forward &alpha;). Basis: DEF, current share "
        "basis. Currency measures in $M; EPS in $/sh; margin in %. Green = actual above "
        "consensus, red = below.", ss["nq_src"]))
    story.append(stat_strip(stats, ss))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Surprise vs. consensus by quarter (% of consensus)", ss["nq_h2"]))
    story.append(surprise_chart(per_q))
    story.append(Spacer(1, 6))

    call = Table([[Paragraph(
        "<b>Narrative read (Focus 3 preview).</b> Across all four quarters Amazon delivered a "
        "consistent profitability beat (EPS +18% to +25%, EBIT well above consensus) on roughly "
        "in-line revenue, while free cash flow came in below consensus every quarter as capex ran "
        "hot (Q4 capex +28% vs. consensus). That margin-beat / cash-pressure divergence is exactly "
        "the quantitative anchor management&rsquo;s narrative gets compared against.", ss["nq_call"])]],
        colWidths=[7.3 * inch])
    call.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CALLBG),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, ACCENT),
    ]))
    story.append(call)
    story.append(Spacer(1, 16))

    story.append(Paragraph("Per-quarter detail", ss["nq_h2"]))
    for qkey in QUARTERS:
        if qkey in per_q:
            story.append(quarter_table(qkey, per_q[qkey], ss))

    doc.build(story)
    print("Wrote", PDF)


if __name__ == "__main__":
    build()
