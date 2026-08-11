"""Altair chart builders for the Roz dashboard (Streamlit-free)."""

from __future__ import annotations

from typing import Any, Sequence

from .company_labels import format_company_label

# Diverging scheme for signed signals (quant z / gap).
_DIVERGING = "redblue"
# Sequential scheme for narrative level (fixed [-2, +2]).
_SEQUENTIAL = "blues"

_NARRATIVE_DOMAIN = [-2.0, 2.0]
_Z_GAP_DOMAIN = [-3.0, 3.0]

_NARRATIVE_SIGNAL_COLS = frozenset(
    {
        "narrative_level",
        "llm_level",
        "mean_narrative_level",
        "mean_narrative_change",
        "change_magnitude",
    }
)
_Z_GAP_SIGNAL_COLS = frozenset(
    {
        "quant_z",
        "gap",
        "narrative_quant_gap",
        "mean_quant_z",
        "mean_narrative_quant_gap",
        "quant_z_pit",
    }
)


def _pd():
    import pandas as pd  # type: ignore

    return pd


def _alt():
    import altair as alt  # type: ignore

    return alt


def _frame(rows: Sequence[dict[str, Any]]):
    pd = _pd()
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        return frame
    if "ticker" in frame.columns and "company" not in frame.columns:
        frame["company"] = frame["ticker"].map(
            lambda value: format_company_label(str(value))
        )
    if "divergence" in frame.columns:
        frame["divergence"] = frame["divergence"].map(bool)
        frame["agreement"] = frame["divergence"].map(
            lambda value: "Divergence" if value else "Aligned"
        )
    return frame


def _period_sort_order(frame) -> list[str]:
    """Sort axis labels; prefer shared calendar ``period`` when present."""
    for col in ("period", "calendar_quarter", "fiscal_period"):
        if col in frame.columns:
            periods = [str(value) for value in frame[col].dropna().unique()]
            if periods:
                return sorted(periods)
    return []


def _signal_scale(signal_col: str, *, center_zero: bool):
    """Fixed color domains — never auto-fit to the selected company range."""
    alt = _alt()
    col = str(signal_col)
    if col in _Z_GAP_SIGNAL_COLS or center_zero:
        return alt.Scale(
            scheme=_DIVERGING,
            domain=list(_Z_GAP_DOMAIN),
            domainMid=0,
            clamp=True,
        )
    if col in _NARRATIVE_SIGNAL_COLS or not center_zero:
        return alt.Scale(
            scheme=_SEQUENTIAL,
            domain=list(_NARRATIVE_DOMAIN),
            clamp=True,
        )
    return alt.Scale(
        scheme=_DIVERGING,
        domain=list(_Z_GAP_DOMAIN),
        domainMid=0,
        clamp=True,
    )


def heatmap_chart(
    rows: Sequence[dict[str, Any]],
    signal_col: str,
    *,
    title: str = "Dimension panel",
    facet_by_company: bool = False,
    center_zero: bool = True,
) -> Any:
    """Rect heatmap: period × dimension, color = signal."""
    alt = _alt()
    frame = _frame(rows)
    if frame.empty or signal_col not in frame.columns:
        return alt.Chart(_pd().DataFrame({"note": ["No data"]})).mark_text().encode(
            text="note:N"
        )

    frame = frame.copy()
    frame["signal"] = _pd().to_numeric(frame[signal_col], errors="coerce")
    if "period" not in frame.columns:
        if "calendar_quarter" in frame.columns:
            frame["period"] = frame["calendar_quarter"].fillna(frame.get("fiscal_period"))
        else:
            frame["period"] = frame.get("fiscal_period")
    period_order = _period_sort_order(frame)
    x_title = (
        "Calendar quarter"
        if "calendar_quarter" in frame.columns
        and frame["calendar_quarter"].notna().any()
        else "Period"
    )

    base = (
        alt.Chart(frame)
        .mark_rect(stroke="#88888833", strokeWidth=0.5)
        .encode(
            x=alt.X(
                "period:N",
                sort=period_order,
                title=x_title,
            ),
            y=alt.Y("dimension:N", title="Dimension", sort=None),
            color=alt.Color(
                "signal:Q",
                title=signal_col.replace("_", " "),
                scale=_signal_scale(signal_col, center_zero=center_zero),
                legend=alt.Legend(orient="right"),
            ),
            tooltip=[
                alt.Tooltip("company:N", title="Company"),
                alt.Tooltip("period:N", title="Calendar quarter"),
                alt.Tooltip("fiscal_period:N", title="Fiscal period"),
                alt.Tooltip("dimension:N", title="Dimension"),
                alt.Tooltip("signal:Q", title="Signal", format=".3f"),
                alt.Tooltip("divergence:N", title="Divergence"),
            ],
        )
        .properties(title=title, height=280)
    )

    if facet_by_company and "company" in frame.columns:
        return (
            base.facet(
                row=alt.Row("company:N", title=None, header=alt.Header(labelAngle=0)),
            )
            .resolve_scale(color="shared")
            .properties(title=title)
        )
    return base


def ranked_bar_chart(
    rows: Sequence[dict[str, Any]],
    value_col: str,
    *,
    title: str = "Cross-company ranking",
    sort_abs: bool = False,
) -> Any:
    """Horizontal bar ranked by *value_col* (company on Y).

    Null values are kept so the full universe still appears (grey / unavailable).
    """
    alt = _alt()
    pd = _pd()
    frame = _frame(rows)
    if frame.empty or value_col not in frame.columns:
        return alt.Chart(pd.DataFrame({"note": ["No data"]})).mark_text().encode(
            text="note:N"
        )

    frame = frame.copy()
    frame["value"] = pd.to_numeric(frame[value_col], errors="coerce")
    n_universe = len(frame)
    if sort_abs:
        frame["_sort"] = frame["value"].abs()
        # Nulls last when sorting descending by abs.
        frame["_sort"] = frame["_sort"].fillna(-1.0)
        sort_field = "_sort"
    else:
        frame["_sort"] = frame["value"].fillna(float("-inf"))
        sort_field = "_sort"
    def _bar_color(value: Any) -> str:
        if pd.isna(value):
            return "#BBBBBB"
        return "#4C78A8" if float(value) >= 0 else "#E45756"

    frame["bar_color"] = frame["value"].map(_bar_color)
    frame["bar_opacity"] = frame["value"].map(
        lambda value: 0.35 if pd.isna(value) else 0.95
    )
    frame["status_note"] = frame["value"].map(
        lambda value: "Signal unavailable" if pd.isna(value) else "ok"
    )

    # Explicit Y domain so every company in the frame appears (no silent truncation).
    ordered = frame.sort_values(sort_field, ascending=False, na_position="last")
    company_domain = [str(value) for value in ordered["company"].tolist()]

    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            y=alt.Y(
                "company:N",
                sort=company_domain,
                scale=alt.Scale(domain=company_domain),
                title=None,
            ),
            x=alt.X("value:Q", title=value_col.replace("_", " ")),
            color=alt.Color("bar_color:N", scale=None, legend=None),
            opacity=alt.Opacity("bar_opacity:Q", legend=None),
            tooltip=[
                alt.Tooltip("company:N", title="Company"),
                alt.Tooltip("value:Q", title="Signal", format=".3f"),
                alt.Tooltip("status_note:N", title="Status"),
                alt.Tooltip("latest_period:N", title="Latest period"),
                alt.Tooltip("quarters:Q", title="Quarters"),
            ],
        )
        .properties(title=title, height=max(280, 28 * n_universe))
    )


def overview_pulse_chart(
    rows: Sequence[dict[str, Any]],
    *,
    title: str = "Latest print: surprise−quant gap",
) -> Any:
    """Attention ranking by absolute surprise−quant gap for latest scorecards.

    Companies with a null gap remain in the chart (grey / unavailable).
    Gap is narrative surprise − quant z (quant clipped to ±2), not level − quant.
    """
    alt = _alt()
    pd = _pd()
    frame = _frame(rows)
    if frame.empty:
        return alt.Chart(pd.DataFrame({"note": ["No data"]})).mark_text().encode(
            text="note:N"
        )

    frame = frame.copy()
    gap_source = frame["gap"] if "gap" in frame.columns else frame.get("narrative_quant_gap")
    frame["gap"] = pd.to_numeric(gap_source, errors="coerce")
    frame["abs_gap"] = frame["gap"].abs()
    # Keep nulls; sort null abs_gap last.
    frame["_sort_abs"] = frame["abs_gap"].fillna(-1.0)
    n_universe = len(frame)
    frame["attention"] = frame.apply(
        lambda row: (
            "Unavailable"
            if pd.isna(row["gap"])
            else (
                "Flagged"
                if bool(row.get("quant_flagged"))
                else ("Incomplete" if bool(row.get("incomplete")) else "OK")
            )
        ),
        axis=1,
    )
    frame["gap_breakdown"] = frame.apply(
        lambda row: (
            "Gap unavailable"
            if pd.isna(row["gap"])
            else "gap = surprise − quant z (quant clipped to ±2); not level − quant"
        ),
        axis=1,
    )
    frame["narrative_level"] = pd.to_numeric(
        frame.get("narrative_level"), errors="coerce"
    )
    frame["narrative_surprise"] = pd.to_numeric(
        frame.get("narrative_surprise"), errors="coerce"
    )
    frame["quant_z"] = pd.to_numeric(frame.get("quant_z"), errors="coerce")

    ordered = frame.sort_values("_sort_abs", ascending=False, na_position="last")
    company_domain = [str(value) for value in ordered["company"].tolist()]

    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            y=alt.Y(
                "company:N",
                sort=company_domain,
                scale=alt.Scale(domain=company_domain),
                title=None,
            ),
            x=alt.X("gap:Q", title="Surprise − quant gap"),
            color=alt.Color(
                "attention:N",
                scale=alt.Scale(
                    domain=["OK", "Incomplete", "Flagged", "Unavailable"],
                    range=["#4C78A8", "#F58518", "#E45756", "#BBBBBB"],
                ),
                title="Status",
            ),
            opacity=alt.condition(
                alt.datum.attention == "Unavailable",
                alt.value(0.35),
                alt.value(0.95),
            ),
            tooltip=[
                alt.Tooltip("company:N", title="Company"),
                alt.Tooltip("fiscal_period:N", title="Fiscal period"),
                alt.Tooltip(
                    "narrative_surprise:Q", title="Narrative surprise", format=".3f"
                ),
                alt.Tooltip("quant_z:Q", title="Quant z", format=".3f"),
                alt.Tooltip("gap:Q", title="Surprise−quant gap", format=".3f"),
                alt.Tooltip(
                    "narrative_level:Q", title="Narrative level (context)", format=".3f"
                ),
                alt.Tooltip("gap_breakdown:N", title="Definition"),
                alt.Tooltip("attention:N", title="Status"),
            ],
        )
        .properties(title=title, height=max(280, 28 * n_universe))
    )


def narrative_quant_scatter(
    rows: Sequence[dict[str, Any]],
    *,
    title: str = "Narrative vs quant",
    color_by_company: bool = True,
) -> Any:
    """Scatter with readable mark sizes; divergences emphasized, never size=0/1."""
    alt = _alt()
    pd = _pd()
    frame = _frame(rows)
    if frame.empty:
        return alt.Chart(pd.DataFrame({"note": ["No data"]})).mark_text().encode(
            text="note:N"
        )

    frame = frame.copy()
    frame["mark_size"] = frame["divergence"].map(lambda value: 120 if value else 55)

    color_encoding = (
        alt.Color("company:N", title="Company", legend=alt.Legend(orient="right"))
        if color_by_company and frame["company"].nunique() > 1
        else alt.Color(
            "agreement:N",
            title="Agreement",
            scale=alt.Scale(
                domain=["Aligned", "Divergence"],
                range=["#4C78A8", "#E45756"],
            ),
        )
    )

    points = (
        alt.Chart(frame)
        .mark_circle(opacity=0.85)
        .encode(
            x=alt.X(
                "quant_z:Q",
                title="Quant z",
                scale=alt.Scale(domain=list(_Z_GAP_DOMAIN), clamp=True),
            ),
            y=alt.Y(
                "narrative_level:Q",
                title="Narrative level",
                scale=alt.Scale(domain=list(_NARRATIVE_DOMAIN), clamp=True),
            ),
            size=alt.Size(
                "mark_size:Q",
                title=None,
                legend=None,
                scale=alt.Scale(range=[55, 120]),
            ),
            color=color_encoding,
            shape=alt.Shape(
                "agreement:N",
                scale=alt.Scale(
                    domain=["Aligned", "Divergence"],
                    range=["circle", "triangle-up"],
                ),
                title="Agreement",
            ),
            tooltip=[
                alt.Tooltip("company:N", title="Company"),
                alt.Tooltip("fiscal_period:N", title="Period"),
                alt.Tooltip("dimension:N", title="Dimension"),
                alt.Tooltip("narrative_level:Q", title="Narrative", format=".3f"),
                alt.Tooltip("quant_z:Q", title="Quant z", format=".3f"),
                alt.Tooltip("gap:Q", title="Gap", format=".3f"),
                alt.Tooltip("agreement:N", title="Agreement"),
            ],
        )
        .properties(title=title, height=420)
    )

    # Diagonal guide where narrative ≈ quant (rough visual anchor).
    guide = (
        alt.Chart(
            pd.DataFrame(
                {
                    "x": [_Z_GAP_DOMAIN[0], _Z_GAP_DOMAIN[1]],
                    "y": [_NARRATIVE_DOMAIN[0], _NARRATIVE_DOMAIN[1]],
                }
            )
        )
        .mark_line(strokeDash=[4, 4], color="#88888888")
        .encode(x="x:Q", y="y:Q")
    )
    return guide + points

def _plotly():
    import plotly.graph_objects as go  # type: ignore

    return go


def _nvq_point_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    from .nvq_analytics import point_key

    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["company"] = format_company_label(str(item.get("ticker") or ""))
        item["point_id"] = point_key(item)
        agreement = str(item.get("agreement") or "")
        if not agreement:
            agreement = "Divergence" if item.get("divergence") else "Aligned"
            item["agreement"] = agreement
        out.append(item)
    return out


def narrative_quant_plotly(
    rows: Sequence[dict[str, Any]],
    *,
    title: str = "Narrative vs quant",
    color_by_company: bool = True,
    selected_keys: Sequence[str] | None = None,
) -> Any:
    """Interactive Plotly scatter for Narrative vs Quant (zoom / brush / click)."""
    go = _plotly()
    frame = _nvq_point_rows(rows)
    selected = {str(key) for key in (selected_keys or ())}
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[_Z_GAP_DOMAIN[0], _Z_GAP_DOMAIN[1]],
            y=[_NARRATIVE_DOMAIN[0], _NARRATIVE_DOMAIN[1]],
            mode="lines",
            line=dict(color="rgba(136,136,136,0.55)", dash="dash", width=1),
            hoverinfo="skip",
            showlegend=False,
            name="diagonal",
        )
    )
    if not frame:
        fig.update_layout(title=title, height=480)
        return fig

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in frame:
        if color_by_company:
            key = str(row.get("company") or row.get("ticker") or "")
        else:
            key = str(row.get("agreement") or "Aligned")
        groups.setdefault(key, []).append(row)

    for group_name, group_rows in groups.items():
        xs = [row.get("quant_z") for row in group_rows]
        ys = [row.get("narrative_level") for row in group_rows]
        ids = [row["point_id"] for row in group_rows]
        symbols = [
            "triangle-up" if row.get("agreement") == "Divergence" else "circle"
            for row in group_rows
        ]
        sizes = []
        for row in group_rows:
            base = 12 if row.get("agreement") == "Divergence" else 9
            if row["point_id"] in selected:
                base += 4
            streak = int(row.get("diverge_streak") or 0) + int(
                row.get("align_streak") or 0
            )
            if streak > 1:
                base += min(4, streak - 1)
            sizes.append(base)
        line_widths = [
            2.5 if row.get("agreement_flipped") else 0.8 for row in group_rows
        ]
        line_colors = [
            "#222222" if row.get("agreement_flipped") else "rgba(0,0,0,0.25)"
            for row in group_rows
        ]
        custom = [
            [
                row.get("ticker"),
                row.get("fiscal_period"),
                row.get("calendar_quarter"),
                row.get("dimension"),
                row.get("gap"),
                row.get("agreement"),
                row.get("peer_gap_delta"),
                row.get("diverge_streak"),
                row.get("align_streak"),
                row["point_id"],
            ]
            for row in group_rows
        ]
        color = None
        if not color_by_company:
            color = "#E45756" if group_name == "Divergence" else "#4C78A8"
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers",
                name=group_name,
                ids=ids,
                customdata=custom,
                marker=dict(
                    size=sizes,
                    symbol=symbols,
                    color=color,
                    line=dict(width=line_widths, color=line_colors),
                    opacity=0.88,
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Fiscal %{customdata[1]} | Cal %{customdata[2]}<br>"
                    "Dim %{customdata[3]}<br>"
                    "Narrative %{y:.3f} | Quant %{x:.3f}<br>"
                    "Gap %{customdata[4]} | %{customdata[5]}<br>"
                    "Peer ? %{customdata[6]}<br>"
                    "Streak D/A %{customdata[7]}/%{customdata[8]}"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title=title,
        height=480,
        dragmode="zoom",
        legend=dict(orientation="v"),
        xaxis=dict(
            title="Quant z",
            range=list(_Z_GAP_DOMAIN),
            zeroline=True,
        ),
        yaxis=dict(
            title="Narrative level",
            range=list(_NARRATIVE_DOMAIN),
            zeroline=True,
        ),
        margin=dict(l=50, r=20, t=50, b=40),
        clickmode="event+select",
    )
    return fig


def narrative_quant_trajectory_plotly(
    rows: Sequence[dict[str, Any]],
    *,
    title: str = "Narrative vs quant trajectory",
    selected_keys: Sequence[str] | None = None,
) -> Any:
    """One connected trajectory per ticker (ordered by calendar quarter)."""
    go = _plotly()
    from .nvq_analytics import period_sort_key, point_calendar_quarter

    frame = _nvq_point_rows(rows)
    selected = {str(key) for key in (selected_keys or ())}
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[_Z_GAP_DOMAIN[0], _Z_GAP_DOMAIN[1]],
            y=[_NARRATIVE_DOMAIN[0], _NARRATIVE_DOMAIN[1]],
            mode="lines",
            line=dict(color="rgba(136,136,136,0.55)", dash="dash", width=1),
            hoverinfo="skip",
            showlegend=False,
            name="diagonal",
        )
    )
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in frame:
        by_ticker.setdefault(str(row.get("ticker") or "").upper(), []).append(row)
    for ticker, group in by_ticker.items():
        group.sort(key=lambda row: period_sort_key(point_calendar_quarter(row)))
        xs = [row.get("quant_z") for row in group]
        ys = [row.get("narrative_level") for row in group]
        ids = [row["point_id"] for row in group]
        sizes = [14 if row["point_id"] in selected else 10 for row in group]
        symbols = [
            "triangle-up" if row.get("agreement") == "Divergence" else "circle"
            for row in group
        ]
        line_widths = [
            2.5 if row.get("agreement_flipped") else 1.0 for row in group
        ]
        custom = [
            [
                row.get("ticker"),
                row.get("fiscal_period"),
                row.get("calendar_quarter"),
                row.get("dimension"),
                row.get("gap"),
                row.get("agreement"),
                row["point_id"],
            ]
            for row in group
        ]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines+markers",
                name=format_company_label(ticker),
                ids=ids,
                customdata=custom,
                marker=dict(
                    size=sizes,
                    symbol=symbols,
                    line=dict(width=line_widths, color="#222222"),
                ),
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Fiscal %{customdata[1]} | Cal %{customdata[2]}<br>"
                    "Dim %{customdata[3]} | %{customdata[5]}<br>"
                    "Narrative %{y:.3f} | Quant %{x:.3f} | Gap %{customdata[4]}"
                    "<extra></extra>"
                ),
            )
        )
    fig.update_layout(
        title=title,
        height=480,
        dragmode="zoom",
        xaxis=dict(title="Quant z", range=list(_Z_GAP_DOMAIN), zeroline=True),
        yaxis=dict(
            title="Narrative level", range=list(_NARRATIVE_DOMAIN), zeroline=True
        ),
        margin=dict(l=50, r=20, t=50, b=40),
        clickmode="event+select",
    )
    return fig
