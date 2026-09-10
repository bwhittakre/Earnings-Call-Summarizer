"""Call Scorecard view for Claims Desk and Post-Call Brief.

Primary visual is a live call-sequence chart: every FY quarter and every
conference / investor day, in calendar order. Y-axis is transparency.
Delivery is tooltip-only until a promise settles — never plotted as zero.

The delivery-vs-transparency quadrant is a secondary layer for settled
points only.

Two view modes (st.radio):
  A — Company Timeline  : one ticker, all calls connected in time
  B — Period Snapshot   : one call, all tickers as transparency bars
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from services.earnings_monitor.period_keys import (
    call_chrono_key,
    period_kind,
    period_label,
    period_sort_key,
)

# Altair import guarded — charts degrade to tables if altair not installed.
try:
    import altair as alt
    _ALTAIR = True
except ImportError:
    _ALTAIR = False

_SIDECAR = Path(__file__).resolve().parents[3] / "data" / "desk_call_scorecard_v1.json"

# ── quadrant colours ──────────────────────────────────────────────────────────
_QUAD_COLOUR = {
    "Credible & Committed": "#2ecc71",   # green  (top-right)
    "Aspirational":         "#f39c12",   # amber  (top-left)
    "Quietly Delivering":   "#3498db",   # blue   (bottom-right)
    "Retreating":           "#e74c3c",   # red    (bottom-left)
    "Insufficient data":    "#bdc3c7",   # grey
}

_TYPE_COLOUR = {
    "Earnings": "#1f4e79",
    "Conference": "#7d3c98",
}

_SIDECAR_HELP = (
    "Scorecard sidecar not found at `data/desk_call_scorecard_v1.json`. "
    "Run `python scripts/_desk_call_scorecard.py` to generate it."
)


# ── data loading ──────────────────────────────────────────────────────────────

def load_desk_scorecard_sidecar() -> dict:
    """Return the full scorecard sidecar payload, or {} on miss/error."""
    if not _SIDECAR.is_file():
        return {}
    try:
        return json.loads(_SIDECAR.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _load_entries(sidecar: Path | None = None) -> list[dict]:
    path = sidecar or _SIDECAR
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("entries") or []
    except Exception:
        return []


def scored_delivery(entry: dict) -> float | None:
    """Delivery is a rate only when a terminal was scored.

    First-seed books can write ``delivery_score=0.0`` because an unparsed
    seed age trips the horizon soft-miss (``n_failed_frac``). That is not
    a keep rate. Unresolved stays a dash.
    """
    confirmed = int(entry.get("n_confirmed") or 0)
    failed = int(entry.get("n_failed") or 0)
    if confirmed + failed == 0:
        return None
    raw = entry.get("delivery_score")
    return raw if raw is not None else None


def _quadrant(delivery: float | None, transparency: float | None) -> str:
    if delivery is None or transparency is None:
        return "Insufficient data"
    high_d = delivery >= 0.5
    # Transparency midpoint: 0.3 (most companies discuss ~30% of goals per quarter)
    high_t = transparency >= 0.3
    if high_d and high_t:
        return "Credible & Committed"
    if not high_d and high_t:
        return "Aspirational"
    if high_d and not high_t:
        return "Quietly Delivering"
    return "Retreating"


def _enrich(entries: list[dict]) -> list[dict]:
    """Add quadrant label and display-friendly columns."""
    out = []
    for e in entries:
        d = scored_delivery(e)
        tr = e.get("transparency_score")
        out.append({
            **e,
            "quadrant": _quadrant(d, tr),
            "delivery_pct": round(d * 100, 1) if d is not None else None,
            "transparency_fmt": round(tr, 2) if tr is not None else None,
            "label": f"{e.get('ticker','')} {e.get('fiscal_period','')}",
        })
    return out


# ── row prep (all calls, including unsettled) ─────────────────────────────────

def _axis_label(fp: str, event_name: str | None) -> str:
    text = str(fp or "").strip()
    if period_kind(text) == "fy" and text.startswith("FY") and "-Q" in text:
        year, _, quarter = text[2:].partition("-Q")
        return f"FY{year[-2:]}-Q{quarter}"
    name = str(event_name or "").strip()
    if name:
        return name if len(name) <= 22 else name[:20] + "…"
    return text.replace("CONF-", "") or "—"


def timeline_rows(entries: list[dict]) -> list[dict]:
    """Display rows for every call. Delivery stays blank when unsettled."""
    used: set[str] = set()
    rows: list[dict] = []
    for entry in sorted(entries, key=lambda r: call_chrono_key(r.get("fiscal_period"))):
        fp = str(entry.get("fiscal_period") or "")
        event = entry.get("event_name")
        kind = entry.get("period_kind") or period_kind(fp)
        call_type = "Conference" if kind == "conf" else "Earnings"
        axis = _axis_label(fp, event)
        if axis in used:
            axis = f"{axis} {fp[-5:]}"
        used.add(axis)
        delivery = scored_delivery(entry)
        transparency = entry.get("transparency_score")
        open_trees = int(entry.get("open_trees_at_call") or 0)
        new_seeds = int(entry.get("n_new_seeds") or 0)
        rows.append({
            **entry,
            "call_type": call_type,
            "axis_label": axis,
            "full_label": period_label(fp, event),
            "chrono": call_chrono_key(fp).isoformat(),
            "delivery_label": f"{delivery:.0%}" if delivery is not None else "—",
            "transparency_plot": float(transparency) if transparency is not None else 0.0,
            "delivery_status": "Settled" if delivery is not None else "Open book",
            "weight": max(open_trees, new_seeds, 1),
            "quadrant": entry.get("quadrant") or _quadrant(delivery, transparency),
        })
    return rows


def _selected_fiscal_period(event: Any) -> str | None:
    """Read the clicked call from a Streamlit Altair selection event."""
    if event is None:
        return None
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    if selection is None:
        return None
    points = getattr(selection, "points", None)
    if points is None and isinstance(selection, dict):
        points = (
            selection.get("points")
            or selection.get("call")
            or next((v for v in selection.values() if isinstance(v, list)), None)
        )
    if not points:
        return None
    first = points[0]
    if isinstance(first, dict):
        return first.get("fiscal_period")
    return None


def _render_interactive_chart(st: Any, chart: Any, key: str) -> Any:
    """Live Altair chart: hover, legend filter, click-to-select when supported."""
    try:
        return st.altair_chart(
            chart,
            use_container_width=True,
            on_select="rerun",
            key=key,
        )
    except TypeError:
        st.altair_chart(chart, use_container_width=True, key=key)
        return None


# ── Altair chart helpers ──────────────────────────────────────────────────────

def _quadrant_background() -> "alt.LayerChart":
    """Four faint coloured rectangles behind the scatter.

    X: delivery [0, 1], Y: transparency [0, 1].
    Midpoints: delivery=0.5, transparency=0.3.
    """
    quads = [
        {"x1": 0.5, "x2": 1.0, "y1": 0.3, "y2": 1.0, "fill": "#d5f5e3"},  # top-right:  Credible & Committed
        {"x1": 0.0, "x2": 0.5, "y1": 0.3, "y2": 1.0, "fill": "#fef9e7"},  # top-left:   Aspirational
        {"x1": 0.5, "x2": 1.0, "y1": 0.0, "y2": 0.3, "fill": "#eaf4fb"},  # bottom-right: Quietly Delivering
        {"x1": 0.0, "x2": 0.5, "y1": 0.0, "y2": 0.3, "fill": "#fdedec"},  # bottom-left: Retreating
    ]
    bg = (
        alt.Chart(alt.Data(values=quads))
        .mark_rect(opacity=0.35)
        .encode(
            x=alt.X("x1:Q", scale=alt.Scale(domain=[0, 1])),
            x2=alt.X2("x2:Q"),
            y=alt.Y("y1:Q"),
            y2=alt.Y2("y2:Q"),
            color=alt.Color("fill:N", scale=None, legend=None),
        )
    )
    labels = (
        alt.Chart(alt.Data(values=[
            {"lx": 0.76, "ly": 0.90, "t": "Credible &\nCommitted"},
            {"lx": 0.24, "ly": 0.90, "t": "Aspirational"},
            {"lx": 0.76, "ly": 0.05, "t": "Quietly\nDelivering"},
            {"lx": 0.24, "ly": 0.05, "t": "Retreating"},
        ]))
        .mark_text(fontSize=11, fontStyle="italic", opacity=0.5, color="#555")
        .encode(
            x=alt.X("lx:Q"),
            y=alt.Y("ly:Q"),
            text=alt.Text("t:N"),
        )
    )
    return bg + labels


def _call_sequence_chart(rows: list[dict], ticker: str) -> "alt.LayerChart":
    """Company Timeline: every call in calendar order. Delivery is tooltip-only."""
    import altair as alt

    if not rows:
        return alt.Chart(alt.Data(values=[])).mark_point()

    labels = [r["axis_label"] for r in rows]
    pick = alt.selection_point(name="call", fields=["fiscal_period"], empty=True)
    kind_pick = alt.selection_point(fields=["call_type"], bind="legend")

    line = (
        alt.Chart(alt.Data(values=rows))
        .mark_line(color="#9aa5b1", strokeWidth=1.5)
        .encode(
            x=alt.X("axis_label:N", sort=labels, axis=alt.Axis(title="Call", labelAngle=-40)),
            y=alt.Y(
                "transparency_plot:Q",
                scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(title="Transparency", format=".0%"),
            ),
            order=alt.Order("chrono:T"),
        )
    )

    dots = (
        alt.Chart(alt.Data(values=rows))
        .mark_point(filled=True)
        .encode(
            x=alt.X("axis_label:N", sort=labels),
            y=alt.Y("transparency_plot:Q", scale=alt.Scale(domain=[0, 1])),
            color=alt.Color(
                "call_type:N",
                scale=alt.Scale(
                    domain=list(_TYPE_COLOUR),
                    range=list(_TYPE_COLOUR.values()),
                ),
                legend=alt.Legend(title="Call type"),
            ),
            shape=alt.Shape(
                "delivery_status:N",
                scale=alt.Scale(domain=["Settled", "Open book"], range=["circle", "triangle"]),
                legend=alt.Legend(title="Delivery"),
            ),
            size=alt.Size(
                "weight:Q",
                scale=alt.Scale(range=[80, 360]),
                legend=alt.Legend(title="Open goals / new seeds"),
            ),
            opacity=alt.condition(pick, alt.value(1.0), alt.value(0.35)),
            tooltip=[
                alt.Tooltip("full_label:N", title="Call"),
                alt.Tooltip("call_type:N", title="Type"),
                alt.Tooltip("transparency_plot:Q", title="Transparency", format=".0%"),
                alt.Tooltip("delivery_label:N", title="Delivery"),
                alt.Tooltip("n_new_seeds:Q", title="New goals"),
                alt.Tooltip("open_trees_at_call:Q", title="Open goals"),
                alt.Tooltip("n_never_touched:Q", title="Never touched"),
                alt.Tooltip("n_silent:Q", title="Silent"),
            ],
        )
    )

    return (
        (line + dots)
        .add_params(pick, kind_pick)
        .transform_filter(kind_pick)
        .properties(
            title=f"{ticker} — every tracked call",
            height=420,
        )
    )


def _snapshot_transparency_chart(rows: list[dict], period_title: str) -> "alt.Chart":
    """Period Snapshot: every ticker at this call, even when delivery is blank."""
    import altair as alt

    if not rows:
        return alt.Chart(alt.Data(values=[])).mark_point()

    pick = alt.selection_point(name="call", fields=["ticker"], empty=True)
    return (
        alt.Chart(alt.Data(values=rows))
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .add_params(pick)
        .encode(
            x=alt.X("ticker:N", sort="-y", axis=alt.Axis(title="Ticker", labelAngle=-40)),
            y=alt.Y(
                "transparency_plot:Q",
                scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(title="Transparency", format=".0%"),
            ),
            color=alt.Color(
                "call_type:N",
                scale=alt.Scale(
                    domain=list(_TYPE_COLOUR),
                    range=list(_TYPE_COLOUR.values()),
                ),
                legend=alt.Legend(title="Call type"),
            ),
            opacity=alt.condition(pick, alt.value(1.0), alt.value(0.35)),
            tooltip=[
                alt.Tooltip("ticker:N", title="Ticker"),
                alt.Tooltip("full_label:N", title="Call"),
                alt.Tooltip("transparency_plot:Q", title="Transparency", format=".0%"),
                alt.Tooltip("delivery_label:N", title="Delivery"),
                alt.Tooltip("n_new_seeds:Q", title="New goals"),
                alt.Tooltip("open_trees_at_call:Q", title="Open goals"),
                alt.Tooltip("n_never_touched:Q", title="Never touched"),
            ],
        )
        .properties(
            title=f"Transparency — {period_title}",
            height=380,
        )
    )


def _scatter_timeline(df_records: list[dict], ticker: str) -> "alt.LayerChart":
    """Settled-only quadrant: one ticker, periods with a delivery rate."""
    import altair as alt

    data = [r for r in df_records if r.get("ticker") == ticker
            and scored_delivery(r) is not None
            and r.get("transparency_score") is not None]
    data.sort(key=lambda r: call_chrono_key(r.get("fiscal_period")))

    if not data:
        return alt.Chart(alt.Data(values=[])).mark_point()

    # Connect dots in temporal order
    line = (
        alt.Chart(alt.Data(values=data))
        .mark_line(color="#aaa", strokeWidth=1, strokeDash=[4, 3])
        .encode(
            x=alt.X("delivery_score:Q",
                    scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(title="Delivery Score →", format=".0%")),
            y=alt.Y("transparency_score:Q",
                    scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(title="↑ Transparency Score")),
            order=alt.Order("fiscal_period:N"),
        )
    )

    dots = (
        alt.Chart(alt.Data(values=data))
        .mark_circle(size=80)
        .encode(
            x=alt.X("delivery_score:Q", scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("transparency_score:Q", scale=alt.Scale(domain=[0, 1])),
            color=alt.Color(
                "quadrant:N",
                scale=alt.Scale(
                    domain=list(_QUAD_COLOUR),
                    range=list(_QUAD_COLOUR.values()),
                ),
                legend=alt.Legend(title="Quadrant"),
            ),
            tooltip=[
                alt.Tooltip("fiscal_period:N", title="Period"),
                alt.Tooltip("event_name:N", title="Event"),
                alt.Tooltip("delivery_score:Q", title="Delivery", format=".1%"),
                alt.Tooltip("transparency_score:Q", title="Transparency", format=".2f"),
                alt.Tooltip("n_confirmed:Q", title="Delivered"),
                alt.Tooltip("n_failed:Q", title="Failed"),
                alt.Tooltip("n_new_seeds:Q", title="New goals"),
                alt.Tooltip("n_never_touched:Q", title="Never touched"),
            ],
        )
    )

    # Period labels on dots
    text = (
        alt.Chart(alt.Data(values=data))
        .mark_text(dx=6, dy=-8, fontSize=9, color="#333")
        .encode(
            x=alt.X("delivery_score:Q", scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("transparency_score:Q", scale=alt.Scale(domain=[0, 1])),
            text=alt.Text("fiscal_period:N"),
        )
    )

    bg = _quadrant_background()
    return (bg + line + dots + text).properties(
        title=f"{ticker} — Delivery vs Transparency over time",
        width=640, height=420,
    ).resolve_scale(color="independent")


def _scatter_snapshot(df_records: list[dict], fiscal_period: str) -> "alt.LayerChart":
    """Period Snapshot: one period, all tickers as labeled dots."""
    import altair as alt

    data = [r for r in df_records if r.get("fiscal_period") == fiscal_period
            and scored_delivery(r) is not None
            and r.get("transparency_score") is not None]

    if not data:
        return alt.Chart(alt.Data(values=[])).mark_point()

    dots = (
        alt.Chart(alt.Data(values=data))
        .mark_circle(size=90)
        .encode(
            x=alt.X("delivery_score:Q",
                    scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(title="Delivery Score →", format=".0%")),
            y=alt.Y("transparency_score:Q",
                    scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(title="↑ Transparency Score")),
            color=alt.Color(
                "quadrant:N",
                scale=alt.Scale(
                    domain=list(_QUAD_COLOUR),
                    range=list(_QUAD_COLOUR.values()),
                ),
                legend=alt.Legend(title="Quadrant"),
            ),
            tooltip=[
                alt.Tooltip("ticker:N", title="Ticker"),
                alt.Tooltip("delivery_score:Q", title="Delivery", format=".1%"),
                alt.Tooltip("transparency_score:Q", title="Transparency", format=".2f"),
                alt.Tooltip("n_confirmed:Q", title="Delivered"),
                alt.Tooltip("n_failed:Q", title="Failed"),
                alt.Tooltip("n_new_seeds:Q", title="New goals"),
                alt.Tooltip("n_never_touched:Q", title="Never touched"),
            ],
        )
    )

    labels_snapshot = (
        alt.Chart(alt.Data(values=data))
        .mark_text(dx=6, dy=-9, fontSize=10, fontWeight="bold")
        .encode(
            x=alt.X("delivery_score:Q", scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("transparency_score:Q", scale=alt.Scale(domain=[0, 1])),
            text=alt.Text("ticker:N"),
            color=alt.Color("quadrant:N", scale=alt.Scale(
                domain=list(_QUAD_COLOUR),
                range=list(_QUAD_COLOUR.values()),
            ), legend=None),
        )
    )

    bg = _quadrant_background()
    return (bg + dots + labels_snapshot).properties(
        title=f"All companies — {fiscal_period}",
        width=640, height=420,
    ).resolve_scale(color="independent")


# ── goal-health strip ─────────────────────────────────────────────────────────

def _goal_health_metrics(st: Any, entry: dict) -> None:
    """Three-metric strip: open goals, never touched, stale."""
    open_t = int(entry.get("open_trees_at_call") or 0)
    never  = int(entry.get("n_never_touched") or 0)
    stale  = int(entry.get("n_open_stale") or 0)
    pct_nt = float(entry.get("pct_never_touched") or 0.0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open goals", open_t)
    c2.metric("Never touched", never,
              delta=f"{pct_nt:.0%} of open" if open_t else None,
              delta_color="inverse")
    c3.metric("Stale > 4 qtrs", stale, delta_color="inverse")
    c4.metric("Touched ≥ once", open_t - never if open_t else 0)


# ── main render ───────────────────────────────────────────────────────────────

def render_scorecard(st: Any, sector_tickers: list[str] | None = None) -> None:
    """Render the call scorecard: live timeline of every call, plus settled quadrant."""
    st.subheader("Call Scorecard")
    st.caption(
        "Every tracked call is on the chart — earnings, conferences, and investor days. "
        "Y-axis is transparency (share of open goals management discussed). "
        "Delivery stays blank until a promise settles; it is never plotted as zero. "
        "Click a point to pin goal health. Use the legend to show or hide call types. "
        "Settled promises also appear on the delivery-vs-transparency quadrant."
    )

    entries = _load_entries()
    if not entries:
        st.warning(_SIDECAR_HELP)
        return

    entries = _enrich(entries)

    # Filter to sector tickers if provided
    if sector_tickers:
        sector_set = {t.upper() for t in sector_tickers}
        sector_entries = [e for e in entries if str(e.get("ticker","")).upper() in sector_set]
    else:
        sector_entries = entries

    if not sector_entries:
        st.info("No scorecard entries for the current sector filter.")
        return

    # View-mode selector
    view = st.radio(
        "View mode",
        ["Company Timeline", "Period Snapshot"],
        horizontal=True,
        key="scorecard_view_mode",
    )

    all_tickers = sorted({e["ticker"] for e in sector_entries})
    all_periods = sorted(
        {e["fiscal_period"] for e in sector_entries},
        key=period_sort_key,
    )

    # Prefer a ticker that already has a delivery rate; otherwise any ticker.
    scored_tickers = sorted({
        e["ticker"] for e in sector_entries if scored_delivery(e) is not None
    })

    # ── View A: Company Timeline ──────────────────────────────────────────────
    if view == "Company Timeline":
        # Default to the first ticker that has scored data; fall back to first ticker
        default_ticker_idx = 0
        if scored_tickers and all_tickers:
            first_scored = scored_tickers[0]
            if first_scored in all_tickers:
                default_ticker_idx = all_tickers.index(first_scored)
        ticker = st.selectbox("Ticker", all_tickers, index=default_ticker_idx, key="scorecard_ticker")
        ticker_entries = [e for e in sector_entries if e["ticker"] == ticker]

        if not ticker_entries:
            st.info(f"No scorecard rows for {ticker} yet.")
            return

        rows = timeline_rows(ticker_entries)
        selected_fp = None
        if rows and _ALTAIR:
            event = _render_interactive_chart(
                st,
                _call_sequence_chart(rows, ticker),
                key=f"scorecard_seq_{ticker}",
            )
            selected_fp = _selected_fiscal_period(event)
            settled = [e for e in ticker_entries if scored_delivery(e) is not None]
            if settled:
                with st.expander("Settled promises — delivery vs transparency"):
                    st.altair_chart(
                        _scatter_timeline(sector_entries, ticker),
                        use_container_width=True,
                    )
        elif not _ALTAIR:
            st.warning("Altair not installed — showing table.")

        # Clicked call, else most recent by calendar date
        focus = next((e for e in ticker_entries if e.get("fiscal_period") == selected_fp), None)
        if focus is None:
            focus = max(ticker_entries, key=lambda e: call_chrono_key(e["fiscal_period"]))
        st.caption(
            f"Goal health — {period_label(focus['fiscal_period'], focus.get('event_name'))}"
        )
        _goal_health_metrics(st, focus)

        # Data table
        with st.expander("Scorecard data"):
            st.dataframe(
                [
                    {
                        "period": period_label(e["fiscal_period"], e.get("event_name")),
                        "kind": e.get("period_kind") or period_kind(e["fiscal_period"]),
                        "delivery": f"{scored_delivery(e):.1%}" if scored_delivery(e) is not None else "—",
                        "transparency": f"{e['transparency_score']:.2f}" if e.get("transparency_score") is not None else "—",
                        "quadrant": e["quadrant"],
                        "delivered": e.get("n_confirmed", 0),
                        "failed": e.get("n_failed", 0),
                        "new_goals": e.get("n_new_seeds", 0),
                        "never_touched": e.get("n_never_touched", 0),
                        "stale": e.get("n_open_stale", 0),
                    }
                    for e in sorted(ticker_entries, key=lambda e: call_chrono_key(e["fiscal_period"]))
                ],
                hide_index=True,
                use_container_width=True,
            )

    # ── View B: Period Snapshot ───────────────────────────────────────────────
    else:
        include_conf = st.checkbox(
            "Include conferences / investor days",
            value=False,
            key="scorecard_include_conf",
            help="Off keeps the cross-ticker snapshot on earnings quarters only.",
        )
        snapshot_periods = [
            p for p in all_periods
            if include_conf or period_kind(p) == "fy"
        ]
        if not snapshot_periods:
            st.info("No FY quarters in this filter. Enable conferences to see event rows.")
            return
        default_idx = len(snapshot_periods) - 1
        period = st.selectbox(
            "Fiscal period",
            snapshot_periods,
            index=default_idx,
            key="scorecard_period",
            format_func=lambda p: period_label(
                p,
                next(
                    (e.get("event_name") for e in sector_entries if e.get("fiscal_period") == p),
                    None,
                ),
            ),
        )
        period_entries = [
            e for e in sector_entries if e["fiscal_period"] == period
        ]

        if not period_entries:
            st.info(f"No scorecard rows for {period} yet.")
            return

        period_rows = timeline_rows(period_entries)
        period_title = period_label(
            period,
            next((e.get("event_name") for e in period_entries), None),
        )
        if period_rows and _ALTAIR:
            _render_interactive_chart(
                st,
                _snapshot_transparency_chart(period_rows, period_title),
                key=f"scorecard_snap_{period}",
            )
            settled = [e for e in period_entries if scored_delivery(e) is not None]
            if settled:
                with st.expander("Settled promises — delivery vs transparency"):
                    st.altair_chart(
                        _scatter_snapshot(sector_entries, period),
                        use_container_width=True,
                    )
        elif not _ALTAIR:
            st.warning("Altair not installed — showing table.")

        # Quad summary counts
        from collections import Counter
        counts = Counter(e["quadrant"] for e in period_entries)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Credible & Committed", counts.get("Credible & Committed", 0))
        c2.metric("Aspirational", counts.get("Aspirational", 0))
        c3.metric("Quietly Delivering", counts.get("Quietly Delivering", 0))
        c4.metric("Retreating", counts.get("Retreating", 0))

        # Data table
        with st.expander("Scorecard data"):
            st.dataframe(
                sorted(
                    [
                        {
                            "ticker": e["ticker"],
                            "delivery": f"{scored_delivery(e):.1%}" if scored_delivery(e) is not None else "—",
                            "transparency": f"{e['transparency_score']:.2f}" if e.get("transparency_score") is not None else "—",
                            "quadrant": e["quadrant"],
                            "delivered": e.get("n_confirmed", 0),
                            "failed": e.get("n_failed", 0),
                            "new_goals": e.get("n_new_seeds", 0),
                            "never_touched": e.get("n_never_touched", 0),
                        }
                        for e in period_entries
                    ],
                    key=lambda r: r["ticker"],
                ),
                hide_index=True,
                use_container_width=True,
            )
