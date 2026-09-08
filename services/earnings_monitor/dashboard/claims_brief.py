"""Post-Call Brief — data assembly and rendering.

Surfaces claims desk + management regime signals as a single readable view
designed for the 5-day window between an earnings call and consensus reactions.

No LLM calls. All signals are read from pre-computed sidecars:
  - data/desk_call_scorecard_v1.json
  - Structured Narrative/output/cross_company/json/desk_regimes_v1.json
  - Structured Narrative/output/cross_company/json/desk_claims_v1.json
  - DashboardData.company_history(ticker)   [optional, for narrative context]
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

_SCORECARD_PATH = ROOT / "data" / "desk_call_scorecard_v1.json"
_REGIMES_PATH = (
    ROOT
    / "Structured Narrative"
    / "output"
    / "cross_company"
    / "json"
    / "desk_regimes_v1.json"
)
_CLAIMS_PATH = (
    ROOT
    / "Structured Narrative"
    / "output"
    / "cross_company"
    / "json"
    / "desk_claims_v1.json"
)

_FY_RE = __import__("re").compile(r"^FY(\d{4})-Q([1-4])$", __import__("re").IGNORECASE)


def _fkey(fp: str | None) -> tuple[int, int]:
    m = _FY_RE.fullmatch(str(fp or "").strip().upper())
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


def _fmt_rate(v: float | None) -> str:
    return f"{v:.0%}" if v is not None else "—"


def _fmt_eng(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}"


# ── data structures ───────────────────────────────────────────────────────────

@dataclass
class RegimeInfo:
    named_person: str
    role: str
    start_fiscal: str | None
    end_fiscal: str | None
    succession_type: str | None
    deliver_rate: float | None
    n_trees: int


@dataclass
class BriefData:
    ticker: str
    fiscal_period: str

    # Scorecard signals
    delivery_score: float | None
    engagement_score: float | None
    n_confirmed: int
    n_failed: int
    n_new_seeds: int
    n_restated: int
    n_dropped: int
    n_deferred: int
    n_silent: int
    n_never_touched: int
    n_open_stale: int
    open_trees_at_call: int
    pct_never_touched: float

    # Delivery history for sparkline (sorted oldest→newest)
    history: list[dict] = field(default_factory=list)

    # Regime
    active_regime: RegimeInfo | None = None
    prior_regime: RegimeInfo | None = None

    # Resolved trees this period
    delivered_this_period: list[dict] = field(default_factory=list)
    missed_or_dropped_this_period: list[dict] = field(default_factory=list)

    # Watch list
    clocks_due_soon: list[dict] = field(default_factory=list)     # open + clock_due_next
    never_touched_trees: list[dict] = field(default_factory=list)  # open + never cited

    # Narrative context from Roz
    narrative_level: float | None = None
    narrative_change: float | None = None
    quant_z: float | None = None

    @property
    def quadrant(self) -> str:
        d, e = self.delivery_score, self.engagement_score
        if d is None or e is None:
            return "Insufficient data"
        if d >= 0.5 and e >= 0.0:
            return "Credible & Committed"
        if d < 0.5 and e >= 0.0:
            return "Aspirational"
        if d >= 0.5 and e < 0.0:
            return "Quietly Delivering"
        return "Retreating"

    @property
    def quadrant_color(self) -> str:
        return {
            "Credible & Committed": "#2ecc71",
            "Aspirational": "#f39c12",
            "Quietly Delivering": "#3498db",
            "Retreating": "#e74c3c",
        }.get(self.quadrant, "#bdc3c7")


# ── loaders ───────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_scorecard_entries() -> list[dict]:
    return _load_json(_SCORECARD_PATH).get("entries") or []


def _load_regimes() -> dict:
    return _load_json(_REGIMES_PATH)


def _load_claims_rows() -> list[dict]:
    return _load_json(_CLAIMS_PATH).get("rows") or []


# ── assembly ──────────────────────────────────────────────────────────────────

def _resolve_regime_info(
    ticker: str,
    fiscal_period: str,
    reg_data: dict,
) -> tuple[RegimeInfo | None, RegimeInfo | None]:
    """Return (active_regime, prior_regime) for ticker at fiscal_period."""
    regimes_list = reg_data.get("regimes") or []
    books = reg_data.get("books") or {}

    def _regime_rate(rid: str) -> tuple[float | None, int]:
        for bk in books.values():
            rr = (bk.get("regime_rates") or {}).get(rid)
            if rr:
                counts = rr.get("known_delivered_counts") or {}
                return (
                    counts.get("known_delivered_rate"),
                    int(rr.get("n_trees") or 0),
                )
        return None, 0

    ticker_up = ticker.upper()
    fp_key = _fkey(fiscal_period)

    # Collect this ticker's regimes sorted by start
    ticker_regimes = sorted(
        [r for r in regimes_list
         if str(r.get("ticker") or "").upper() == ticker_up],
        key=lambda r: _fkey(r.get("start_fiscal")),
    )
    if not ticker_regimes:
        return None, None

    # Active = last regime whose start <= fiscal_period (or first if none qualify)
    active_raw = ticker_regimes[0]
    for r in ticker_regimes:
        if _fkey(r.get("start_fiscal")) <= fp_key:
            active_raw = r

    active_idx = ticker_regimes.index(active_raw)
    prior_raw = ticker_regimes[active_idx - 1] if active_idx > 0 else None

    def _build(raw: dict) -> RegimeInfo:
        rid = str(raw.get("regime_id") or "")
        rate, n_trees = _regime_rate(rid)
        return RegimeInfo(
            named_person=str(raw.get("named_person") or "Unknown"),
            role=str(raw.get("role") or "CEO"),
            start_fiscal=raw.get("start_fiscal"),
            end_fiscal=raw.get("end_fiscal"),
            succession_type=raw.get("succession_type"),
            deliver_rate=rate,
            n_trees=n_trees,
        )

    return _build(active_raw), (_build(prior_raw) if prior_raw else None)


def load_brief_data(
    ticker: str,
    fiscal_period: str,
    *,
    dashboard_data: Any | None = None,
) -> BriefData | None:
    """Assemble all signals for the brief. Returns None if no scorecard entry exists."""
    ticker_up = ticker.strip().upper()
    fp_key = _fkey(fiscal_period)
    if fp_key[0] < 0:
        return None

    # ── scorecard ──────────────────────────────────────────────────────────────
    sc_entries = _load_scorecard_entries()
    ticker_entries = [
        e for e in sc_entries if str(e.get("ticker") or "").upper() == ticker_up
    ]
    ticker_entries.sort(key=lambda e: _fkey(e.get("fiscal_period")))

    this_entry = next(
        (e for e in ticker_entries if e.get("fiscal_period") == fiscal_period), None
    )
    if this_entry is None:
        return None

    # History = all entries for this ticker sorted oldest→newest
    history = ticker_entries

    # ── regimes ───────────────────────────────────────────────────────────────
    reg_data = _load_regimes()
    active_regime, prior_regime = _resolve_regime_info(ticker_up, fiscal_period, reg_data)

    # ── claims rows ───────────────────────────────────────────────────────────
    all_rows = _load_claims_rows()
    ticker_rows = [
        r for r in all_rows if str(r.get("ticker") or "").upper() == ticker_up
    ]

    # Resolved this period: next_fiscal_period == fiscal_period
    resolved_this = [
        r for r in ticker_rows if r.get("next_fiscal_period") == fiscal_period
    ]
    delivered_this = [
        r for r in resolved_this if r.get("delivery") == "delivered"
    ]
    missed_this = [
        r for r in resolved_this
        if r.get("delivery") not in ("delivered", "unresolved", None)
        or r.get("state") in ("subject-changed",)
    ]

    # Watch list
    open_rows = [r for r in ticker_rows if r.get("state") == "open"]
    clocks_due_soon = [r for r in open_rows if r.get("clock_due_next")]
    never_touched = [
        r for r in open_rows
        if not r.get("follow_up_status") and not r.get("next_fiscal_period")
    ]

    # ── narrative context from Roz ────────────────────────────────────────────
    narrative_level = None
    narrative_change = None
    quant_z = None
    if dashboard_data is not None:
        try:
            history_rows = dashboard_data.company_history(ticker_up)
            match_row = next(
                (h for h in history_rows if h.get("fiscal_period") == fiscal_period), None
            )
            if match_row:
                narrative_level = match_row.get("narrative_level")
                narrative_change = match_row.get("narrative_change")
                quant_z = match_row.get("quant_z")
        except Exception:
            pass

    return BriefData(
        ticker=ticker_up,
        fiscal_period=fiscal_period,
        delivery_score=this_entry.get("delivery_score"),
        engagement_score=this_entry.get("engagement_score"),
        n_confirmed=int(this_entry.get("n_confirmed") or 0),
        n_failed=int(this_entry.get("n_failed") or 0),
        n_new_seeds=int(this_entry.get("n_new_seeds") or 0),
        n_restated=int(this_entry.get("n_restated") or 0),
        n_dropped=int(this_entry.get("n_dropped") or 0),
        n_deferred=int(this_entry.get("n_deferred") or 0),
        n_silent=int(this_entry.get("n_silent") or 0),
        n_never_touched=int(this_entry.get("n_never_touched") or 0),
        n_open_stale=int(this_entry.get("n_open_stale") or 0),
        open_trees_at_call=int(this_entry.get("open_trees_at_call") or 0),
        pct_never_touched=float(this_entry.get("pct_never_touched") or 0.0),
        history=history,
        active_regime=active_regime,
        prior_regime=prior_regime,
        delivered_this_period=delivered_this,
        missed_or_dropped_this_period=missed_this,
        clocks_due_soon=clocks_due_soon,
        never_touched_trees=never_touched,
        narrative_level=narrative_level,
        narrative_change=narrative_change,
        quant_z=quant_z,
    )


def all_scored_periods(ticker: str) -> list[str]:
    """Return all fiscal periods with a scorecard entry for this ticker, newest first."""
    ticker_up = ticker.strip().upper()
    entries = [
        e for e in _load_scorecard_entries()
        if str(e.get("ticker") or "").upper() == ticker_up
    ]
    return [
        e["fiscal_period"]
        for e in sorted(entries, key=lambda e: _fkey(e.get("fiscal_period")), reverse=True)
        if e.get("fiscal_period")
    ]


def all_scored_tickers() -> list[str]:
    """All tickers that have at least one scorecard entry, alphabetically."""
    return sorted({
        str(e.get("ticker") or "").upper()
        for e in _load_scorecard_entries()
        if e.get("ticker")
    })


# ── Streamlit renderer ────────────────────────────────────────────────────────

def render_brief(st: Any, brief: "BriefData") -> None:
    """Render the full post-call brief inside the Streamlit page."""

    # ── Header ────────────────────────────────────────────────────────────────
    quad = brief.quadrant
    quad_color = brief.quadrant_color
    eng_arrow = "↑" if (brief.engagement_score or 0) >= 0 else "↓"
    eng_sign = "+" if (brief.engagement_score or 0) >= 0 else ""

    col_title, col_badge = st.columns([3, 1])
    with col_title:
        st.subheader(f"{brief.ticker} — {brief.fiscal_period}")
        st.caption(
            f"Engagement this call: {eng_arrow} {eng_sign}{_fmt_eng(brief.engagement_score)}  |  "
            f"Delivery rate: {_fmt_rate(brief.delivery_score)}  |  "
            f"Open goals at call: {brief.open_trees_at_call}"
        )
    with col_badge:
        st.markdown(
            f"<div style='background:{quad_color};padding:10px 8px;border-radius:6px;"
            f"text-align:center;color:white;font-weight:bold;font-size:13px;margin-top:12px'>"
            f"{quad}</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Track Record + Regime ─────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Track Record**")
        # Delivery trend: last 5 periods with data
        scored = [
            h for h in brief.history
            if h.get("delivery_score") is not None
        ][-5:]
        if scored:
            trend_rows = [
                {
                    "period": h["fiscal_period"],
                    "delivery": f"{h['delivery_score']:.0%}",
                    "engagement": _fmt_eng(h.get("engagement_score")),
                    "quadrant": _quadrant_short(h.get("delivery_score"), h.get("engagement_score")),
                }
                for h in scored
            ]
            st.dataframe(trend_rows, hide_index=True, use_container_width=True)
        else:
            st.caption("No prior scored periods.")

    with col_right:
        st.markdown("**Management Regime**")
        if brief.active_regime:
            r = brief.active_regime
            st.markdown(
                f"**{r.named_person}** ({r.role})  \n"
                f"Since {r.start_fiscal or 'unknown'}  \n"
                f"Regime deliver rate: **{_fmt_rate(r.deliver_rate)}** "
                f"across {r.n_trees} tracked promise{'s' if r.n_trees != 1 else ''}"
            )
            if brief.prior_regime:
                pr = brief.prior_regime
                st.caption(
                    f"Prior regime: {pr.named_person} — "
                    f"{_fmt_rate(pr.deliver_rate)} on {pr.n_trees} promises"
                )
        else:
            st.caption("No regime data for this ticker.")

    st.divider()

    # ── This Call: engagement breakdown ──────────────────────────────────────
    st.markdown("**This Call — Engagement Breakdown**")
    eng_cols = st.columns(6)
    _metric(eng_cols[0], "New goals", brief.n_new_seeds)
    _metric(eng_cols[1], "Restated", brief.n_restated)
    _metric(eng_cols[2], "Delivered", brief.n_confirmed, delta_color="normal")
    _metric(eng_cols[3], "Failed", brief.n_failed, delta_color="inverse")
    _metric(eng_cols[4], "Deferred", brief.n_deferred, delta_color="inverse")
    _metric(eng_cols[5], "Silent", brief.n_silent, delta_color="inverse",
            help_text="Open goals management did not mention this call")

    st.divider()

    # ── Resolved this period / Watch list ─────────────────────────────────────
    tab_resolved, tab_watch = st.tabs(
        [
            f"Resolved this period ({len(brief.delivered_this_period) + len(brief.missed_or_dropped_this_period)})",
            f"Watch list ({len(brief.clocks_due_soon) + len(brief.never_touched_trees) + brief.n_open_stale})",
        ]
    )

    with tab_resolved:
        if brief.delivered_this_period:
            st.markdown("**Delivered**")
            for row in brief.delivered_this_period:
                with st.expander(_row_title(row), expanded=False):
                    st.caption(f"Seeded {row.get('fiscal_period')} · {row.get('claim_type','')}")
                    st.write(row.get("excerpt", ""))
                    if row.get("follow_up_excerpt"):
                        st.markdown("*Follow-up cite:*")
                        st.write(row["follow_up_excerpt"])
        if brief.missed_or_dropped_this_period:
            st.markdown("**Not delivered / subject changed**")
            for row in brief.missed_or_dropped_this_period:
                with st.expander(_row_title(row), expanded=False):
                    st.caption(f"Seeded {row.get('fiscal_period')} · state: {row.get('state')}")
                    st.write(row.get("excerpt", ""))
        if not brief.delivered_this_period and not brief.missed_or_dropped_this_period:
            st.caption("No promises had a follow-up cite recorded in this specific period.")

    with tab_watch:
        if brief.clocks_due_soon:
            st.markdown("**Clocks due next quarter**")
            for row in brief.clocks_due_soon:
                with st.expander(_row_title(row), expanded=False):
                    st.caption(f"Seeded {row.get('fiscal_period')} · clock: {row.get('clock','?')}")
                    st.write(row.get("excerpt", ""))

        if brief.never_touched_trees:
            st.markdown(f"**Ghost commitments — never cited again ({len(brief.never_touched_trees)})**")
            for row in brief.never_touched_trees[:8]:  # cap at 8
                with st.expander(_row_title(row), expanded=False):
                    st.caption(f"Seeded {row.get('fiscal_period')} · never followed up")
                    st.write(row.get("excerpt", ""))

        if brief.n_open_stale:
            st.markdown(f"**Stale goals — no cite in >4 quarters: {brief.n_open_stale}**")
            st.caption("These open promises have not been mentioned in over a year. Check the claims desk for details.")

        if not brief.clocks_due_soon and not brief.never_touched_trees and not brief.n_open_stale:
            st.caption("Watch list is clear for this ticker.")

    # ── Narrative context ─────────────────────────────────────────────────────
    if any(v is not None for v in [brief.narrative_level, brief.narrative_change, brief.quant_z]):
        st.divider()
        st.markdown("**Narrative Context** *(from Roz)*")
        nc_cols = st.columns(3)
        _metric(nc_cols[0], "Narrative level", _fmt_float(brief.narrative_level),
                help_text="LLM-scored tone: -2 (bearish) to +2 (bullish)")
        _metric(nc_cols[1], "Narrative change", _fmt_float(brief.narrative_change),
                help_text="Change vs prior quarter")
        _metric(nc_cols[2], "Quant z-score", _fmt_float(brief.quant_z),
                help_text="EPS/Sales surprise z-score vs peer universe")


# ── helpers ───────────────────────────────────────────────────────────────────

def _quadrant_short(d: float | None, e: float | None) -> str:
    if d is None or e is None:
        return "—"
    if d >= 0.5 and e >= 0.0:
        return "C&C"
    if d < 0.5 and e >= 0.0:
        return "Asp"
    if d >= 0.5 and e < 0.0:
        return "QD"
    return "Ret"


def _row_title(row: dict) -> str:
    objs = row.get("objects") or []
    if isinstance(objs, (list, tuple)) and objs:
        return str(objs[0])
    excerpt = str(row.get("excerpt") or "")
    return excerpt[:60] + ("…" if len(excerpt) > 60 else "")


def _metric(col: Any, label: str, value: Any, *, delta_color: str = "off",
            help_text: str | None = None) -> None:
    col.metric(label, str(value) if value is not None else "—",
               delta_color=delta_color, help=help_text)


def _fmt_float(v: float | None, decimals: int = 2) -> str:
    return f"{v:.{decimals}f}" if v is not None else "—"


# ── markdown generator ────────────────────────────────────────────────────────

def generate_brief_markdown(brief: "BriefData") -> str:
    """Generate a compact markdown brief suitable for saving to disk or forwarding."""
    lines: list[str] = [
        f"# Post-Call Brief: {brief.ticker} — {brief.fiscal_period}",
        "",
        f"**Quadrant:** {brief.quadrant}  ",
        f"**Delivery rate:** {_fmt_rate(brief.delivery_score)}  ",
        f"**Engagement score:** {_fmt_eng(brief.engagement_score)}  ",
        f"**Open goals at call:** {brief.open_trees_at_call}",
        "",
        "---",
        "",
        "## Management Regime",
    ]
    if brief.active_regime:
        r = brief.active_regime
        lines += [
            f"- **{r.named_person}** ({r.role}), since {r.start_fiscal or 'unknown'}",
            f"- Regime deliver rate: **{_fmt_rate(r.deliver_rate)}** on {r.n_trees} promises",
        ]
        if brief.prior_regime:
            pr = brief.prior_regime
            lines.append(
                f"- Prior regime ({pr.named_person}): {_fmt_rate(pr.deliver_rate)} on {pr.n_trees} promises"
            )
    else:
        lines.append("- No regime data available.")

    lines += [
        "",
        "## This Call — Engagement",
        "",
        f"| Metric | Count |",
        f"|---|---|",
        f"| New goals | {brief.n_new_seeds} |",
        f"| Restated | {brief.n_restated} |",
        f"| Delivered | {brief.n_confirmed} |",
        f"| Failed | {brief.n_failed} |",
        f"| Deferred | {brief.n_deferred} |",
        f"| Dropped | {brief.n_dropped} |",
        f"| Silent (not mentioned) | {brief.n_silent} |",
        "",
        "## Resolved This Period",
    ]

    if brief.delivered_this_period:
        lines.append("\n**Delivered:**")
        for row in brief.delivered_this_period:
            lines.append(f"- {_row_title(row)} *(seeded {row.get('fiscal_period')})*")
    if brief.missed_or_dropped_this_period:
        lines.append("\n**Not delivered / subject changed:**")
        for row in brief.missed_or_dropped_this_period:
            lines.append(f"- {_row_title(row)} *(seeded {row.get('fiscal_period')})*")
    if not brief.delivered_this_period and not brief.missed_or_dropped_this_period:
        lines.append("- No follow-up cites recorded for this specific period.")

    lines += [
        "",
        "## Watch List",
    ]
    if brief.clocks_due_soon:
        lines.append("\n**Clocks due next quarter:**")
        for row in brief.clocks_due_soon:
            lines.append(f"- {_row_title(row)} *(seeded {row.get('fiscal_period')}, clock {row.get('clock','?')})*")
    if brief.never_touched_trees:
        lines.append(f"\n**Ghost commitments (never cited again): {len(brief.never_touched_trees)}**")
        for row in brief.never_touched_trees[:5]:
            lines.append(f"- {_row_title(row)} *(seeded {row.get('fiscal_period')})*")
    if brief.n_open_stale:
        lines.append(f"\n**Stale goals (no cite > 4 quarters):** {brief.n_open_stale}")
    if not brief.clocks_due_soon and not brief.never_touched_trees and not brief.n_open_stale:
        lines.append("- Watch list clear.")

    if any(v is not None for v in [brief.narrative_level, brief.narrative_change, brief.quant_z]):
        lines += [
            "",
            "## Narrative Context",
            "",
            f"| Narrative level | Narrative change | Quant z-score |",
            f"|---|---|---|",
            f"| {_fmt_float(brief.narrative_level)} | {_fmt_float(brief.narrative_change)} | {_fmt_float(brief.quant_z)} |",
        ]

    return "\n".join(lines)
