"""Management Regimes Roz view. Read-only. No new LLM.

Four modes via st.radio:
    A — Company timeline   : Gantt chart of CEO tenures
    B — Regime comparison  : current vs prior CEO performance
    C — Transfer ledger    : trees that crossed a regime boundary
    D — Multi-company      : ranked overview across all tracked tickers

Reads desk_regimes_v1.json sidecar. Degrades gracefully if sidecar missing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts._desk_regimes import (
    current_regime,
    load_management_regimes,
    regime_rate_counts,
    regimes_for_ticker,
    transition_fiscals,
)
from scripts._desk_trees_v2 import fiscal_key
from services.earnings_monitor.dashboard.company_labels import format_company_label

REGIMES_STAMP = "2026-09-01T16:00:00+00:00"
REGIMES_FILENAME = "desk_regimes_v1.json"

_TRANSFER_KIND_LABELS: dict[str, str] = {
    "single_regime":               "Single regime",
    "prior_closed":                "Closed before transition",
    "inherited_adopted":           "Adopted by new regime",
    "inherited_closed_by_successor": "Closed by successor",
    "inherited_overdue":           "Inherited — overdue",
    "inherited_ignored":           "Inherited — ignored",
}

_MODE_TIMELINE   = "A — Company timeline"
_MODE_COMPARISON = "B — Regime comparison"
_MODE_LEDGER     = "C — Transfer ledger"
_MODE_OVERVIEW   = "D — Multi-company overview"
_MODES = [_MODE_TIMELINE, _MODE_COMPARISON, _MODE_LEDGER, _MODE_OVERVIEW]


# ─────────────────────────────────────────────────────────────────────────────
# Loader
# ─────────────────────────────────────────────────────────────────────────────

def _cross_company_json(
    history_source: str | os.PathLike[str] | None = None,
) -> Path:
    raw = os.environ.get(
        "HISTORY_SOURCE",
        str(history_source) if history_source else "Structured Narrative/output",
    )
    root = Path(raw)
    if root.name == "cross_company":
        return root / "json"
    if root.name == "output" or (root / "cross_company").is_dir():
        return root / "cross_company" / "json"
    return root / "output" / "cross_company" / "json"


def load_desk_regimes_v1(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Load the desk_regimes_v1.json sidecar.  Returns None if missing or stale."""
    path = _cross_company_json(history_source) / REGIMES_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("generated_at") or "") != REGIMES_STAMP:
        return None
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_rate(value: float | None, *, pct: bool = True) -> str:
    if value is None:
        return "—"
    if pct:
        return f"{value:.0%}"
    return f"{value:.2f}"


def _fmt_regime_label(regime: dict) -> str:
    person = regime.get("named_person") or "Unknown"
    start = regime.get("start_fiscal") or "?"
    end = regime.get("end_fiscal") or "present"
    return f"{person} ({start}–{end})"


def _known_del_rate(counts: dict) -> float | None:
    return counts.get("known_delivered_rate")


def _settled_share(counts: dict) -> float | None:
    return counts.get("settled_share")


# ─────────────────────────────────────────────────────────────────────────────
# Mode A — Company timeline (Gantt)
# ─────────────────────────────────────────────────────────────────────────────

def _gantt_chart(regimes_for_tick: list[dict]) -> Any | None:
    """Return an Altair Gantt chart for a single ticker's CEO timeline."""
    try:
        import altair as alt
        import pandas as pd
    except ImportError:
        return None
    if not regimes_for_tick:
        return None
    rows = []
    for r in regimes_for_tick:
        start = r.get("start_fiscal") or "FY2016-Q1"
        end = r.get("end_fiscal") or "FY2027-Q4"
        rows.append(
            {
                "Person": r.get("named_person") or r.get("regime_id"),
                "Role": r.get("role") or "CEO",
                "Start": start,
                "End": end,
                "regime_id": r.get("regime_id"),
                "succession": r.get("succession_type") or "—",
            }
        )
    frame = pd.DataFrame(rows)
    # Encode fiscal labels as ordinal using a consistent fiscal sort key
    all_fps: list[str] = sorted(
        set(list(frame["Start"]) + list(frame["End"])),
        key=fiscal_key,
    )
    base = (
        alt.Chart(frame)
        .mark_bar(height=20, cornerRadiusEnd=3)
        .encode(
            x=alt.X("Start:O", sort=all_fps, title="Start fiscal", axis=alt.Axis(labelAngle=-45)),
            x2=alt.X2("End:O"),
            y=alt.Y("Person:N", title=None),
            color=alt.Color("Role:N", title="Role", scale=alt.Scale(scheme="tableau10")),
            tooltip=[
                alt.Tooltip("Person:N", title="Person"),
                alt.Tooltip("Role:N", title="Role"),
                alt.Tooltip("Start:O", title="Start fiscal"),
                alt.Tooltip("End:O", title="End fiscal"),
                alt.Tooltip("succession:N", title="Succession"),
            ],
        )
        .properties(height=max(60 * len(rows), 100), title="CEO tenure timeline")
    )
    return base


def _render_mode_a(st: Any, ticker: str, regimes: list[dict], book_block: dict | None) -> None:
    """Mode A: single-company timeline + rate metrics."""
    tick_regimes = regimes_for_ticker(ticker, regimes)
    if not tick_regimes:
        st.info(f"No regime entries found for {ticker}.")
        return

    chart = _gantt_chart(tick_regimes)
    if chart is not None:
        st.altair_chart(chart, use_container_width=True)
    else:
        # Fallback: text table
        for r in tick_regimes:
            st.markdown(
                f"**{r.get('named_person')}** — {r.get('start_fiscal')} to "
                f"{r.get('end_fiscal') or 'present'} "
                f"(*{r.get('succession_type') or 'ongoing'}*)"
            )

    # Mark transition points
    transitions = transition_fiscals(ticker, regimes)
    if transitions:
        st.caption(f"CEO transitions at: {', '.join(transitions)}")

    # Metrics for current regime
    cur = current_regime(ticker, regimes)
    if cur and book_block:
        regime_rates = book_block.get("regime_rates") or {}
        cur_data = regime_rates.get(cur["regime_id"])
        if cur_data:
            counts = cur_data.get("known_delivered_counts") or {}
            n = cur_data.get("n_trees", 0)
            kd = _known_del_rate(counts)
            ss = _settled_share(counts)
            transfer_summary = cur_data.get("transfer_kind_summary") or {}
            n_inh = sum(v for k, v in transfer_summary.items() if k.startswith("inherited"))
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Trees seeded", n)
            c2.metric("Known-delivered rate", _fmt_rate(kd))
            c3.metric("Settled share", _fmt_rate(ss))
            c4.metric("Inherited trees", n_inh)
            st.caption(
                f"Current regime: **{cur['named_person']}** (since {cur['start_fiscal']}). "
                "Rates cover only trees seeded under this CEO. "
                "Prior-regime trees are shown in Transfer Ledger (Mode C)."
            )


# ─────────────────────────────────────────────────────────────────────────────
# Mode B — Regime comparison
# ─────────────────────────────────────────────────────────────────────────────

def _comparison_chart(pairs: list[dict]) -> Any | None:
    """Altair grouped bar: known-delivered rate by regime."""
    try:
        import altair as alt
        import pandas as pd
    except ImportError:
        return None
    if not pairs:
        return None
    rows = []
    for p in pairs:
        rows.append({"Regime": p["label"], "Metric": "Known-delivered", "Rate": p.get("kd")})
        rows.append({"Regime": p["label"], "Metric": "Settled share", "Rate": p.get("ss")})
    frame = pd.DataFrame(rows)
    frame["Rate"] = frame["Rate"].fillna(0)
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("Regime:N", title=None),
            y=alt.Y("Rate:Q", title="Rate", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format=".0%")),
            color=alt.Color("Metric:N", title=None),
            column=alt.Column("Metric:N", title=None),
            tooltip=[
                alt.Tooltip("Regime:N"),
                alt.Tooltip("Metric:N"),
                alt.Tooltip("Rate:Q", format=".0%"),
            ],
        )
        .properties(width=200, title="Known-delivered and settled share by regime")
    )


def _render_mode_b(st: Any, ticker: str, regimes: list[dict], book_block: dict | None) -> None:
    """Mode B: regime comparison — current vs prior."""
    tick_regimes = regimes_for_ticker(ticker, regimes)
    if not tick_regimes:
        st.info(f"No regime entries for {ticker}.")
        return
    if len(tick_regimes) < 2:
        st.info(f"{ticker} has only one tracked regime. Nothing to compare yet.")
        _render_mode_a(st, ticker, regimes, book_block)
        return

    regime_rates = (book_block or {}).get("regime_rates") or {}
    cur = tick_regimes[-1]
    prior = tick_regimes[-2]
    cur_data = regime_rates.get(cur["regime_id"]) or {}
    prior_data = regime_rates.get(prior["regime_id"]) or {}
    cur_counts = cur_data.get("known_delivered_counts") or {}
    prior_counts = prior_data.get("known_delivered_counts") or {}

    col_cur, col_prior = st.columns(2)
    with col_cur:
        st.subheader(f"Current — {cur.get('named_person')}")
        st.caption(f"Regime: {cur.get('start_fiscal')} – present")
        st.metric("Trees seeded", cur_data.get("n_trees", 0))
        st.metric("Known-delivered rate", _fmt_rate(_known_del_rate(cur_counts)))
        st.metric("Settled share", _fmt_rate(_settled_share(cur_counts)))
        n_trees = cur_counts.get("n_aged", 0)
        st.caption(f"Aged trees: {n_trees}")
        # Flag inherited
        ts = cur_data.get("transfer_kind_summary") or {}
        n_inh_over = ts.get("inherited_overdue", 0)
        n_inh_ign = ts.get("inherited_ignored", 0)
        if n_inh_over or n_inh_ign:
            st.warning(
                f"This regime has inherited trees: "
                f"{n_inh_over} overdue, {n_inh_ign} ignored"
            )
    with col_prior:
        st.subheader(f"Prior — {prior.get('named_person')}")
        st.caption(
            f"Regime: {prior.get('start_fiscal')} – {prior.get('end_fiscal') or 'present'}"
        )
        st.metric("Trees seeded", prior_data.get("n_trees", 0))
        st.metric("Known-delivered rate", _fmt_rate(_known_del_rate(prior_counts)))
        st.metric("Settled share", _fmt_rate(_settled_share(prior_counts)))
        n_trees_prior = prior_counts.get("n_aged", 0)
        st.caption(f"Aged trees: {n_trees_prior}")

    # Comparison chart
    pairs = [
        {
            "label": f"{cur.get('named_person')} (current)",
            "kd": _known_del_rate(cur_counts),
            "ss": _settled_share(cur_counts),
        },
        {
            "label": f"{prior.get('named_person')} (prior)",
            "kd": _known_del_rate(prior_counts),
            "ss": _settled_share(prior_counts),
        },
    ]
    chart = _comparison_chart(pairs)
    if chart is not None:
        st.altair_chart(chart, use_container_width=False)


# ─────────────────────────────────────────────────────────────────────────────
# Mode C — Transfer ledger
# ─────────────────────────────────────────────────────────────────────────────

_TRANSFER_FILTER_ALL = "all"
_TRANSFER_FILTER_CHOICES = [_TRANSFER_FILTER_ALL] + [
    k for k in _TRANSFER_KIND_LABELS if k != "single_regime"
]


def _render_mode_c(st: Any, ticker: str, book_block: dict | None) -> None:
    """Mode C: transfer ledger for a ticker."""
    if book_block is None:
        st.info("Regimes sidecar not loaded.")
        return
    ledger: list[dict] = [
        e for e in (book_block.get("transfer_ledger") or [])
        if (str(e.get("ticker") or "")).upper() == ticker.upper()
    ]
    if not ledger:
        st.info(f"No regime-crossing trees found for {ticker}.")
        return

    # Summary metrics
    from collections import Counter
    kind_counts = Counter(e.get("transfer_kind") for e in ledger)
    cols = st.columns(len(kind_counts) + 1)
    cols[0].metric("Inherited total", len(ledger))
    for i, (kind, cnt) in enumerate(sorted(kind_counts.items()), start=1):
        cols[min(i, len(cols) - 1)].metric(
            _TRANSFER_KIND_LABELS.get(kind, kind), cnt
        )

    # Status filter
    kind_filter = st.selectbox(
        "Transfer kind filter",
        _TRANSFER_FILTER_CHOICES,
        key=f"regime_ledger_filter_{ticker}",
    )
    if kind_filter != _TRANSFER_FILTER_ALL:
        ledger = [e for e in ledger if e.get("transfer_kind") == kind_filter]

    # Render table
    try:
        import pandas as pd
        rows = []
        for e in ledger:
            rows.append(
                {
                    "Tree ID": e.get("tree_id"),
                    "Title": e.get("title"),
                    "Transfer kind": _TRANSFER_KIND_LABELS.get(
                        str(e.get("transfer_kind") or ""), str(e.get("transfer_kind") or "")
                    ),
                    "Seed regime": e.get("seed_regime_person") or e.get("seed_regime"),
                    "Seed fiscal": e.get("seed_fiscal"),
                    "Transition": e.get("transition_fiscal"),
                    "Clock": e.get("clock") or "—",
                    "Delivery": e.get("delivery") or "—",
                    "Open": "✓" if e.get("open") else "✗",
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    except ImportError:
        for e in ledger:
            st.markdown(
                f"**{e.get('tree_id')}** — {_TRANSFER_KIND_LABELS.get(str(e.get('transfer_kind') or ''), '')} "
                f"(seed {e.get('seed_fiscal')}, transition {e.get('transition_fiscal')})"
            )

    st.caption(
        "Transfer taxonomy: **inherited_adopted** = new regime actively restated/continued the tree. "
        "**inherited_overdue** = open at transition with a past-due clock. "
        "**inherited_ignored** = open at transition, clock not yet due. "
        "**prior_closed** = closed before the transition. "
        "**inherited_closed_by_successor** = new regime provided the terminal node."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Mode D — Multi-company overview
# ─────────────────────────────────────────────────────────────────────────────

def _multi_company_chart(rows: list[dict]) -> Any | None:
    """Altair grouped bar: current vs prior known-delivered rate per ticker."""
    try:
        import altair as alt
        import pandas as pd
    except ImportError:
        return None
    chart_rows = []
    for row in rows:
        if row.get("kd_current") is not None:
            chart_rows.append(
                {"Ticker": row["ticker"], "Regime": "Current", "Rate": row["kd_current"]}
            )
        if row.get("kd_prior") is not None:
            chart_rows.append(
                {"Ticker": row["ticker"], "Regime": "Prior", "Rate": row["kd_prior"]}
            )
    if not chart_rows:
        return None
    frame = pd.DataFrame(chart_rows)
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("Ticker:N", title=None),
            y=alt.Y("Rate:Q", title="Known-delivered rate", scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(format=".0%")),
            color=alt.Color("Regime:N", title="Regime"),
            xOffset=alt.XOffset("Regime:N"),
            tooltip=[
                alt.Tooltip("Ticker:N"),
                alt.Tooltip("Regime:N"),
                alt.Tooltip("Rate:Q", format=".0%"),
            ],
        )
        .properties(height=280, title="Current vs prior regime known-delivered rate")
    )


def _render_mode_d(
    st: Any,
    regimes: list[dict],
    book_block: dict | None,
    universe: list[str] | None,
) -> None:
    """Mode D: multi-company overview table + chart."""
    if book_block is None:
        st.info("Regimes sidecar not loaded.")
        return

    regime_rates = book_block.get("regime_rates") or {}
    all_tickers = sorted(
        set(str(r.get("ticker") or "").upper() for r in regimes if r.get("ticker"))
    )
    if universe:
        universe_upper = [t.upper() for t in universe]
        all_tickers = [t for t in all_tickers if t in universe_upper]

    table_rows: list[dict] = []
    for ticker in all_tickers:
        tick_regimes = regimes_for_ticker(ticker, regimes)
        if not tick_regimes:
            continue
        cur = tick_regimes[-1]
        cur_data = regime_rates.get(cur["regime_id"]) or {}
        cur_counts = cur_data.get("known_delivered_counts") or {}
        kd_cur = _known_del_rate(cur_counts)
        ts = cur_data.get("transfer_kind_summary") or {}
        n_overdue = ts.get("inherited_overdue", 0)

        kd_prior: float | None = None
        if len(tick_regimes) >= 2:
            prior = tick_regimes[-2]
            prior_data = regime_rates.get(prior["regime_id"]) or {}
            prior_counts = prior_data.get("known_delivered_counts") or {}
            kd_prior = _known_del_rate(prior_counts)

        table_rows.append(
            {
                "ticker": ticker,
                "kd_current": kd_cur,
                "kd_prior": kd_prior,
                "Ticker": ticker,
                "Current CEO": cur.get("named_person") or "—",
                "CEO since": cur.get("start_fiscal") or "—",
                "Trees (current regime)": cur_data.get("n_trees", 0),
                "KD rate (current)": _fmt_rate(kd_cur),
                "KD rate (prior)": _fmt_rate(kd_prior),
                "Inherited overdue": n_overdue,
            }
        )

    # Sort by current KD rate descending (None sorts last)
    table_rows.sort(
        key=lambda r: (r.get("kd_current") is None, -(r.get("kd_current") or 0))
    )

    try:
        import pandas as pd
        display_cols = [
            "Ticker", "Current CEO", "CEO since",
            "Trees (current regime)", "KD rate (current)", "KD rate (prior)", "Inherited overdue",
        ]
        st.dataframe(
            pd.DataFrame(table_rows)[display_cols],
            use_container_width=True,
            hide_index=True,
        )
    except ImportError:
        for row in table_rows:
            st.markdown(
                f"**{row['Ticker']}** — {row['Current CEO']} — "
                f"KD: {row['KD rate (current)']} vs prior {row['KD rate (prior)']}"
            )

    # Chart: only companies that have a prior regime with data
    companies_with_prior = [r for r in table_rows if r.get("kd_prior") is not None]
    if companies_with_prior:
        chart = _multi_company_chart(companies_with_prior)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        st.caption(
            "Chart shows only companies with ≥2 tracked regimes. "
            "Rates cover trees seeded under each CEO only."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def render_claims_regimes(
    st: Any,
    data: Any,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    """Render the Management Regimes page in Roz.

    Parameters
    ----------
    st : streamlit module
    data : DashboardData (used for book/ticker universe)
    sector_tickers : optional list of tickers to restrict the universe
    sector_choice : optional sector label (for keying widgets)
    """
    sidecar = load_desk_regimes_v1()

    universe: list[str] | None = None
    if sector_tickers is not None:
        universe = [str(t).upper() for t in sector_tickers]

    # Load regimes — prefer from sidecar (already embedded), fall back to disk
    if sidecar and isinstance(sidecar.get("regimes"), list):
        regimes = sidecar["regimes"]
    else:
        regimes = load_management_regimes()

    if not regimes:
        st.warning("Management regimes catalog not found. Run `python scripts/_desk_regimes_builder.py`.")
        return

    if sidecar is None:
        st.warning(
            "Management regimes sidecar (`desk_regimes_v1.json`) is missing or stale. "
            "Metrics will not be shown. Run `python scripts/_desk_regimes_builder.py` to build it."
        )

    # ── Mode selector ────────────────────────────────────────────────────────
    mode = st.radio(
        "View",
        _MODES,
        horizontal=True,
        key=f"regime_mode_{sector_choice or 'all'}",
    )

    # ── Book selector (for modes A, B, C) ────────────────────────────────────
    books_in_sidecar = list((sidecar or {}).get("books", {}).keys()) if sidecar else []

    if mode in (_MODE_TIMELINE, _MODE_COMPARISON, _MODE_LEDGER):
        # Ticker selector
        # Build universe from the sector filter + regimes that have entries
        regime_tickers = sorted(
            set(str(r.get("ticker") or "").upper() for r in regimes if r.get("ticker"))
        )
        if universe:
            regime_tickers = [t for t in regime_tickers if t in universe]
        if not regime_tickers:
            st.info("No tickers in the current universe have regime entries.")
            return

        ticker = st.selectbox(
            "Company",
            regime_tickers,
            key=f"regime_ticker_{mode}_{sector_choice or 'all'}",
        )

        # Find which book this ticker belongs to (for rate lookups)
        book_block = _find_book_for_ticker(ticker, sidecar)

        if mode == _MODE_TIMELINE:
            _render_mode_a(st, ticker, regimes, book_block)
        elif mode == _MODE_COMPARISON:
            _render_mode_b(st, ticker, regimes, book_block)
        elif mode == _MODE_LEDGER:
            _render_mode_c(st, ticker, book_block)

    elif mode == _MODE_OVERVIEW:
        # Find the book block that has the most trees (cross-sector merge)
        # For multi-company overview, merge all book blocks into one view
        merged_block = _merge_book_blocks(sidecar)
        _render_mode_d(st, regimes, merged_block, universe)

    # ── Footer ────────────────────────────────────────────────────────────────
    if sidecar:
        st.caption(
            f"Sidecar stamp {sidecar.get('generated_at')} — "
            f"{len(regimes)} regime entries across all tracked tickers. "
            "CEO-only first pass; CFO entries not yet included."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_book_for_ticker(ticker: str, sidecar: dict | None) -> dict | None:
    """Find the book block that contains the given ticker's regime rates."""
    if sidecar is None:
        return None
    ticker_upper = ticker.upper()
    for book_id, block in (sidecar.get("books") or {}).items():
        regime_rates = block.get("regime_rates") or {}
        for regime_id in regime_rates:
            if regime_id.startswith(ticker_upper.lower() + "-") or regime_id.startswith(ticker_upper.lower() + "_"):
                return block
        # Also check transfer ledger
        for entry in (block.get("transfer_ledger") or []):
            if str(entry.get("ticker") or "").upper() == ticker_upper:
                return block
    # Fallback: return biggest block
    return _merge_book_blocks(sidecar)


def _merge_book_blocks(sidecar: dict | None) -> dict | None:
    """Merge all book blocks into one for multi-company views."""
    if sidecar is None:
        return None
    books = sidecar.get("books") or {}
    if not books:
        return None
    merged_rates: dict = {}
    merged_ledger: list = []
    merged_n = 0
    for block in books.values():
        merged_rates.update(block.get("regime_rates") or {})
        merged_ledger.extend(block.get("transfer_ledger") or [])
        merged_n += block.get("n_trees") or 0
    return {
        "book_id": "merged",
        "n_trees": merged_n,
        "regime_rates": merged_rates,
        "transfer_ledger": merged_ledger,
    }
