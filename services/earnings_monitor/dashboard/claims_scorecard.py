"""2-Axis Call Scorecard view for the Claims Desk page.

Quadrant layout (fixed x-axis orientation):
  X-axis: Delivery Score     (0 = never delivered → 1 = always delivered)
  Y-axis: Transparency Score (0 = all goals silent → 1 = all goals discussed)

  Top-left    → Aspirational         (talking openly but hasn't delivered yet)
  Top-right   → Credible & Committed (delivering AND discussing commitments)
  Bottom-left → Retreating           (not delivering AND going silent on goals)
  Bottom-right→ Quietly Delivering   (delivering without much public commitment)

Two view modes (st.radio):
  A — Company Timeline  : one ticker, scatter of all periods, connected in time
  B — Period Snapshot   : one fiscal period, all tickers as labeled dots
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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
        d = e.get("delivery_score")
        tr = e.get("transparency_score")
        out.append({
            **e,
            "quadrant": _quadrant(d, tr),
            "delivery_pct": round(d * 100, 1) if d is not None else None,
            "transparency_fmt": round(tr, 2) if tr is not None else None,
            "label": f"{e.get('ticker','')} {e.get('fiscal_period','')}",
        })
    return out


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


def _scatter_timeline(df_records: list[dict], ticker: str) -> "alt.LayerChart":
    """Company Timeline: one ticker, all periods, dots connected by time."""
    import altair as alt

    data = [r for r in df_records if r.get("ticker") == ticker
            and r.get("delivery_score") is not None
            and r.get("transparency_score") is not None]
    data.sort(key=lambda r: (r.get("fiscal_period") or ""))

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
            and r.get("delivery_score") is not None
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
    """Render the 2-axis call scorecard inside the Claims Desk page."""
    st.subheader("Call Scorecard — 2-Axis Accountability")
    st.caption(
        "X-axis: rolling delivery rate (promises kept, including deferred/expired/aged misses). "
        "Y-axis: transparency score (fraction of open goals management discussed this call). "
        "Bottom-left = Retreating · Bottom-right = Quietly Delivering · "
        "Top-left = Aspirational · Top-right = Credible & Committed."
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
    all_periods = sorted({e["fiscal_period"] for e in sector_entries},
                         key=lambda p: (int(p[2:6]), int(p[8:])) if len(p) == 10 else (0,0))

    # Tickers that have at least one period with a real delivery_score
    scored_tickers = sorted({
        e["ticker"] for e in sector_entries if e.get("delivery_score") is not None
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
        ticker_entries = [e for e in sector_entries if e["ticker"] == ticker
                          and e.get("delivery_score") is not None]

        if not ticker_entries:
            st.info(f"No scored periods for {ticker} yet.")
            return

        if _ALTAIR:
            chart = _scatter_timeline(sector_entries, ticker)
            st.altair_chart(chart, use_container_width=False)
        else:
            st.warning("Altair not installed — showing table.")

        # Latest-period goal health strip
        latest = max(ticker_entries, key=lambda e: (int(e["fiscal_period"][2:6]), int(e["fiscal_period"][8:])))
        st.caption(f"Goal health — {latest['fiscal_period']}")
        _goal_health_metrics(st, latest)

        # Data table
        with st.expander("Scorecard data"):
            st.dataframe(
                [
                    {
                        "period": e["fiscal_period"],
                        "delivery": f"{e['delivery_score']:.1%}" if e.get("delivery_score") is not None else "—",
                        "transparency": f"{e['transparency_score']:.2f}" if e.get("transparency_score") is not None else "—",
                        "quadrant": e["quadrant"],
                        "delivered": e.get("n_confirmed", 0),
                        "failed": e.get("n_failed", 0),
                        "new_goals": e.get("n_new_seeds", 0),
                        "never_touched": e.get("n_never_touched", 0),
                        "stale": e.get("n_open_stale", 0),
                    }
                    for e in sorted(ticker_entries,
                                    key=lambda e: (int(e["fiscal_period"][2:6]), int(e["fiscal_period"][8:])))
                ],
                hide_index=True,
                use_container_width=True,
            )

    # ── View B: Period Snapshot ───────────────────────────────────────────────
    else:
        # Default to latest period
        default_idx = len(all_periods) - 1
        period = st.selectbox("Fiscal period", all_periods,
                              index=default_idx, key="scorecard_period")
        period_entries = [e for e in sector_entries
                          if e["fiscal_period"] == period
                          and e.get("delivery_score") is not None]

        if not period_entries:
            st.info(f"No scored entries for {period} yet.")
            return

        if _ALTAIR:
            chart = _scatter_snapshot(sector_entries, period)
            st.altair_chart(chart, use_container_width=False)
        else:
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
                            "delivery": f"{e['delivery_score']:.1%}" if e.get("delivery_score") is not None else "—",
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
