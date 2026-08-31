"""Read-only Claims Trees page. NVIDIA gold book. No new LLM."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.earnings_monitor.dashboard.claims_desk import (
    clock_is_due,
    history_backdrop_window,
)
from services.earnings_monitor.dashboard.claims_horizon import (
    HORIZON_CHOICES,
    book_fiscal_span,
    build_horizon_chart,
    fiscal_span,
    horizon_series,
)
from services.earnings_monitor.dashboard.claims_quotes import (
    filter_quote_rows,
    quote_rows,
)
from services.earnings_monitor.dashboard.company_labels import format_company_label
from services.earnings_monitor.dashboard.data import DashboardData

_NVDA_STAMP = "2026-08-27T18:02:00+00:00"
_V1_STAMP = "2026-08-17T17:28:40+00:00"
_OPS_STAMP = "2026-08-31T14:18:00+00:00"
_HC_STAMP = "2026-08-31T14:45:00+00:00"
_TREES_FILENAME = "desk_trees_v2.json"
_OPS_TREES_FILENAME = "desk_trees_ops_v2.json"
_HC_TREES_FILENAME = "desk_trees_hc_v2.json"
_METRICS_FILENAME = "desk_panel_metrics_v2.json"
_QUEUE_FILENAME = "desk_cue_queue_v2.json"
_OPS_QUEUE_INDEX = "desk_cue_queue_ops_v2.json"
_HC_QUEUE_INDEX = "desk_cue_queue_hc_v2.json"
_BOOK_NVDA = "nvda_gold_v2"
_BOOK_OPS = "desk_ops_v2"
_BOOK_HC = "desk_hc_v2"
_HC_SECTORS = frozenset(
    {
        "healthcare_large_cap",
        "healthcare_ex_payers",
        "managed_care",
        "medtech_tools",
        "pharma_biotech",
    }
)
_TECH_SECTORS = frozenset(
    {
        "xlk_tech",
        "tech_core",
        "software_pure",
        "software_cloud",
        "semis_cycle",
        "semiconductors",
        "mega_cap_tech",
        "mega_inbook",
        "equipment",
        "designers",
    }
)
_HC_TICKERS = frozenset(
    {
        "ABBV",
        "ABT",
        "AMGN",
        "BMY",
        "BSX",
        "CI",
        "DHR",
        "ELV",
        "GILD",
        "ISRG",
        "JNJ",
        "LLY",
        "MDT",
        "MRK",
        "PFE",
        "REGN",
        "SYK",
        "TMO",
        "UNH",
        "VRTX",
    }
)


def suggested_book(
    sector_choice: str | None,
    available: Sequence[str],
    custom_tickers: Sequence[str] | None = None,
) -> str:
    """Default book for the Roz sector filter. Gold stays selectable."""
    books = [str(name) for name in available]
    sector = str(sector_choice or "")
    if sector in _HC_SECTORS and _BOOK_HC in books:
        return _BOOK_HC
    if sector in _TECH_SECTORS and _BOOK_OPS in books:
        return _BOOK_OPS
    if sector == "Custom List":
        customs = {
            str(ticker).upper()
            for ticker in (custom_tickers or ())
            if str(ticker).strip()
        }
        if customs and customs <= _HC_TICKERS and _BOOK_HC in books:
            return _BOOK_HC
        if customs == {"NVDA"} and _BOOK_NVDA in books:
            return _BOOK_NVDA
        if _BOOK_OPS in books:
            return _BOOK_OPS
    for name in (_BOOK_NVDA, _BOOK_OPS, _BOOK_HC):
        if name in books:
            return name
    return books[0] if books else _BOOK_NVDA


def scored_rate_caption(n_scoreable: object, kind: str) -> str:
    """Honest footnote. Em dash is not a 0% keep rate."""
    if int(n_scoreable or 0) <= 0:
        return f"No scored {kind} yet. Em dash is not a 0% keep rate."
    return f"Scored {kind} only. Unresolved is an em dash."


def show_trailing_credibility(book_choice: str) -> bool:
    """Locked NVIDIA sidecar stays off ops and healthcare books."""
    return book_choice == _BOOK_NVDA


def load_desk_trees_v2(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read the v2 tree book. Refuse the 17 Aug stamp and any other stamp."""
    path = _cross_company_json(history_source) / _TREES_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    stamp = str(payload.get("generated_at") or "")
    if stamp == _V1_STAMP or stamp != _NVDA_STAMP:
        return None
    return payload


def _cross_company_json(history_source: str | os.PathLike[str] | None) -> Path:
    raw = history_source or os.environ.get(
        "EARNINGS_MONITOR_HISTORY_SOURCE",
        "Structured Narrative/output",
    )
    root = Path(raw)
    if root.name == "cross_company":
        return root / "json"
    if root.name == "output" or (root / "cross_company").is_dir():
        return root / "cross_company" / "json"
    return root / "output" / "cross_company" / "json"


def load_desk_trees_ops_v2(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read the operational book. Refuse gold and 17 Aug stamps."""
    path = _cross_company_json(history_source) / _OPS_TREES_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    stamp = str(payload.get("generated_at") or "")
    if stamp in {_V1_STAMP, _NVDA_STAMP, _HC_STAMP} or stamp != _OPS_STAMP:
        return None
    return payload


def load_desk_trees_hc_v2(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read the healthcare book. Refuse gold, tech ops, and 17 Aug stamps."""
    path = _cross_company_json(history_source) / _HC_TREES_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    stamp = str(payload.get("generated_at") or "")
    if stamp in {_V1_STAMP, _NVDA_STAMP, _OPS_STAMP} or stamp != _HC_STAMP:
        return None
    return payload


def load_desk_cue_queue_ops_v2(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Merge per-ticker ops queues. Empty missed list is omitted by the page."""
    folder = _cross_company_json(history_source)
    index_path = folder / _OPS_QUEUE_INDEX
    missed: list[dict[str, Any]] = []
    n_seedable = 0
    n_covered = 0
    n_missed = 0
    latest = None
    for path in sorted(folder.glob("desk_cue_queue_v2_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        stamp = str(payload.get("generated_at") or "")
        if stamp != _OPS_STAMP:
            continue
        n_seedable += int(payload.get("n_seedable") or 0)
        n_covered += int(payload.get("n_covered") or 0)
        n_missed += int(payload.get("n_missed") or 0)
        latest = payload.get("latest_quarter") or latest
        for row in payload.get("missed") or []:
            if isinstance(row, dict):
                missed.append(row)
    if index_path.is_file() or missed or n_seedable:
        return {
            "generated_at": _OPS_STAMP,
            "latest_quarter": latest,
            "n_seedable": n_seedable,
            "n_covered": n_covered,
            "n_missed": n_missed,
            "missed": missed,
            "gold": None,
        }
    return None


def load_desk_cue_queue_hc_v2(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Merge per-ticker healthcare queues. Tech leftovers stay on the ops book."""
    folder = _cross_company_json(history_source)
    index_path = folder / _HC_QUEUE_INDEX
    missed: list[dict[str, Any]] = []
    n_seedable = 0
    n_covered = 0
    n_missed = 0
    latest = None
    for path in sorted(folder.glob("desk_cue_queue_v2_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        stamp = str(payload.get("generated_at") or "")
        if stamp != _HC_STAMP:
            continue
        n_seedable += int(payload.get("n_seedable") or 0)
        n_covered += int(payload.get("n_covered") or 0)
        n_missed += int(payload.get("n_missed") or 0)
        latest = payload.get("latest_quarter") or latest
        for row in payload.get("missed") or []:
            if isinstance(row, dict):
                missed.append(row)
    if index_path.is_file() or missed or n_seedable:
        return {
            "generated_at": _HC_STAMP,
            "latest_quarter": latest,
            "n_seedable": n_seedable,
            "n_covered": n_covered,
            "n_missed": n_missed,
            "missed": missed,
            "gold": None,
        }
    return None


def load_desk_cue_queue_v2(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read the uncovered-cue queue. Refuse the 17 Aug stamp."""
    path = _cross_company_json(history_source) / _QUEUE_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    stamp = str(payload.get("generated_at") or "")
    if stamp == _V1_STAMP or stamp != _NVDA_STAMP:
        return None
    return payload


def latest_scored_fiscal(
    book: Mapping[str, Any] | None,
    queue: Mapping[str, Any] | None = None,
) -> str | None:
    if queue:
        latest = str(queue.get("latest_quarter") or "").strip()
        if latest:
            return latest
    if not book:
        return None
    trigger = str(book.get("walked_trigger") or "")
    if ":" in trigger:
        return trigger.split(":", 1)[1].strip() or None
    return None


def clock_board(
    trees: Sequence[Mapping[str, Any]],
    latest_fiscal: str | None,
) -> dict[str, list[dict[str, Any]]]:
    """Due / slipped / open-no-clock. Soft someday goals are not due."""
    due: list[dict[str, Any]] = []
    slipped: list[dict[str, Any]] = []
    open_no_clock: list[dict[str, Any]] = []
    as_of = str(latest_fiscal or "").strip()
    for tree in trees:
        if not tree.get("open"):
            continue
        clock = str(tree.get("clock") or "").strip() or None
        row = {
            "tree_id": tree.get("tree_id"),
            "ticker": tree.get("ticker"),
            "title": tree.get("title"),
            "kind": tree.get("kind"),
            "clock": clock,
            "state": tree.get("state"),
            "slipped": bool(tree.get("slipped")),
        }
        if tree.get("slipped"):
            slipped.append(row)
            continue
        if not clock:
            open_no_clock.append(row)
            continue
        if as_of and clock_is_due(clock, as_of):
            due.append(row)
    return {
        "due": due,
        "slipped": slipped,
        "open_no_clock": open_no_clock,
    }


def load_desk_panel_metrics_v2(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read PIT trust/ambition. Refuse the 17 Aug stamp."""
    path = _cross_company_json(history_source) / _METRICS_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    stamp = str(payload.get("generated_at") or "")
    if stamp == _V1_STAMP or stamp != _NVDA_STAMP:
        return None
    return payload


def metrics_by_period(
    payload: Mapping[str, Any] | None,
    ticker: str,
) -> dict[str, dict[str, Any]]:
    want = str(ticker or "").upper()
    found: dict[str, dict[str, Any]] = {}
    if not payload:
        return found
    for row in payload.get("rows") or []:
        if str(row.get("ticker") or "").upper() != want:
            continue
        period = str(row.get("fiscal_period") or "")
        if period:
            found[period] = dict(row)
    return found


def attach_metrics_to_backdrop(
    backdrop: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    attached: list[dict[str, Any]] = []
    for row in backdrop:
        item = dict(row)
        match = metrics.get(str(item.get("fiscal_period") or ""))
        item["desk_trust"] = None if match is None else match.get("desk_trust")
        item["desk_trust_n"] = None if match is None else match.get("desk_trust_n")
        item["desk_ambition"] = None if match is None else match.get("desk_ambition")
        item["desk_ambition_n"] = None if match is None else match.get("desk_ambition_n")
        attached.append(item)
    return attached


def format_rate(rate: object) -> str:
    if rate is None:
        return "—"
    try:
        number = float(rate)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.0%}"


def format_n_rate(rate: object, n: object, yes: object) -> str:
    try:
        count = int(n or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return "—"
    return f"{format_rate(rate)} ({yes}/{count})"


def filter_trees_to_universe(
    trees: Sequence[Mapping[str, Any]],
    universe: Sequence[str] | None,
) -> list[dict[str, Any]]:
    if universe is None:
        return [dict(tree) for tree in trees]
    allowed = {str(ticker).upper() for ticker in universe}
    return [
        dict(tree)
        for tree in trees
        if str(tree.get("ticker") or "").upper() in allowed
    ]


def tree_node_rows(tree: Mapping[str, Any]) -> list[dict[str, Any]]:
    seed = tree.get("seed") or {}
    rows = [
        {
            "fiscal_period": seed.get("fiscal_period"),
            "edge": "seed",
            "excerpt": seed.get("excerpt"),
            "citation": seed.get("citation"),
            "clock": seed.get("clock") or tree.get("clock"),
            "slipped": False,
        }
    ]
    for node in tree.get("nodes") or []:
        rows.append(
            {
                "fiscal_period": node.get("fiscal_period"),
                "edge": node.get("edge"),
                "excerpt": node.get("excerpt"),
                "citation": node.get("citation"),
                "clock": node.get("clock"),
                "slipped": bool(node.get("slipped")),
            }
        )
    return rows


def _render_horizon_panel(st: Any, trees: Sequence[Mapping[str, Any]]) -> None:
    st.subheader("Horizon keep rate")
    st.caption(
        "New series. A due clock with only a silent / slipped edge is a miss "
        "here. Tree delivery stays unresolved. This is not the locked gold "
        "6/7 desk_trust."
    )
    span_start, span_end = book_fiscal_span(trees)
    periods_all = fiscal_span(span_start, span_end)
    if not periods_all:
        st.caption("No dated clocks to score.")
        return
    tickers = sorted(
        {str(tree.get("ticker") or "").upper() for tree in trees if tree.get("ticker")}
    )
    col_h, col_k, col_c = st.columns(3)
    with col_h:
        horizon = st.selectbox("Horizon", list(HORIZON_CHOICES), index=0)
    with col_k:
        kind_choice = st.selectbox("Kind", ("promises", "goals", "both"), index=0)
    with col_c:
        company = st.selectbox("Company", ["all", *tickers], index=0)
    col_a, col_b = st.columns(2)
    with col_a:
        start = st.selectbox("From", periods_all, index=0)
    with col_b:
        end_index = len(periods_all) - 1
        end = st.selectbox("Through", periods_all, index=end_index)
    kinds = None
    if kind_choice == "promises":
        kinds = ("promise",)
    elif kind_choice == "goals":
        kinds = ("goal",)
    focus = None if company == "all" else company
    window_periods = fiscal_span(str(start), str(end))
    series = horizon_series(
        trees,
        window_periods,
        horizon=horizon,
        ticker=focus,
        kinds=kinds,
        window=(str(start), str(end)),
    )
    latest = series[-1] if series else {}
    metric_a, metric_b = st.columns(2)
    with metric_a:
        st.metric(
            "This-window quarterly (last period)",
            format_n_rate(
                latest.get("horizon_quarter_rate"),
                latest.get("horizon_quarter_n"),
                latest.get("horizon_quarter_yes"),
            ),
        )
    with metric_b:
        st.metric(
            "Cumulative in window",
            format_n_rate(
                latest.get("horizon_cum_rate"),
                latest.get("horizon_cum_n"),
                latest.get("horizon_cum_yes"),
            ),
        )
    chart = build_horizon_chart(series)
    if chart is not None:
        try:
            st.altair_chart(chart, use_container_width=True)
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Unable to render horizon chart: {exc}")
    elif series:
        st.dataframe(
            [
                {
                    "fiscal_period": row.get("fiscal_period"),
                    "quarterly": format_n_rate(
                        row.get("horizon_quarter_rate"),
                        row.get("horizon_quarter_n"),
                        row.get("horizon_quarter_yes"),
                    ),
                    "cumulative": format_n_rate(
                        row.get("horizon_cum_rate"),
                        row.get("horizon_cum_n"),
                        row.get("horizon_cum_yes"),
                    ),
                }
                for row in series
            ],
            hide_index=True,
            use_container_width=True,
        )


def _render_quote_table(st: Any, trees: Sequence[Mapping[str, Any]]) -> None:
    rows = quote_rows(trees)
    if not rows:
        return
    st.subheader("Quotes")
    st.caption(
        "Seed, later restatements, and the close. Silent quarters are omitted. "
        "Slipped is a filter tag, not a typed miss."
    )
    outcomes = sorted({str(row.get("outcome") or "") for row in rows})
    tickers = sorted({str(row.get("ticker") or "").upper() for row in rows if row.get("ticker")})
    col_o, col_k, col_r = st.columns(3)
    with col_o:
        picked_outcomes = st.multiselect("Outcome", outcomes, default=outcomes)
    with col_k:
        picked_kinds = st.multiselect("Quote kind", ("promise", "goal"), default=("promise", "goal"))
    with col_r:
        picked_roles = st.multiselect(
            "Role", ("seed", "change", "close"), default=("seed", "change", "close")
        )
    picked_tickers = None
    if len(tickers) > 1:
        picked_tickers = st.multiselect("Quote company", tickers, default=tickers)
    filtered = filter_quote_rows(
        rows,
        outcomes=picked_outcomes,
        kinds=picked_kinds,
        roles=picked_roles,
        tickers=picked_tickers,
    )
    st.dataframe(
        [
            {
                "company": format_company_label(str(row.get("ticker") or "")),
                "fiscal_period": row.get("fiscal_period"),
                "role": row.get("role"),
                "edge": row.get("edge"),
                "kind": row.get("kind"),
                "outcome": row.get("outcome"),
                "claim": row.get("title"),
                "clock": row.get("clock") or "—",
                "excerpt": row.get("excerpt"),
            }
            for row in filtered
        ],
        hide_index=True,
        use_container_width=True,
    )


def last_cited_fiscal(tree: Mapping[str, Any]) -> str | None:
    for node in reversed(list(tree.get("nodes") or [])):
        fiscal = str(node.get("fiscal_period") or "").strip()
        if fiscal:
            return fiscal
    seed = tree.get("seed") or {}
    fiscal = str(seed.get("fiscal_period") or "").strip()
    return fiscal or None


def render_claims_trees(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    gold = load_desk_trees_v2()
    ops = load_desk_trees_ops_v2()
    healthcare = load_desk_trees_hc_v2()
    if gold is None and ops is None and healthcare is None:
        st.info(
            "Claims desk v2 is missing or the stamp is not a recognized book."
        )
        return
    books = [
        name
        for name, payload in (
            (_BOOK_NVDA, gold),
            (_BOOK_OPS, ops),
            (_BOOK_HC, healthcare),
        )
        if payload
    ]
    universe = None
    if sector_tickers is not None:
        universe = [str(ticker).upper() for ticker in sector_tickers]
    default_book = suggested_book(
        sector_choice,
        books,
        custom_tickers=universe if sector_choice == "Custom List" else None,
    )
    book_index = books.index(default_book) if default_book in books else 0
    book_choice = st.selectbox(
        "Book",
        books,
        index=book_index,
        key=f"claims_trees_book_follow_{sector_choice or 'all'}",
    )
    payload = {_BOOK_NVDA: gold, _BOOK_OPS: ops, _BOOK_HC: healthcare}.get(book_choice)
    if payload is None:
        st.info("Selected book is not loaded.")
        return
    trees = filter_trees_to_universe(list(payload.get("trees") or []), universe)
    if not trees and book_choice == _BOOK_NVDA:
        st.info("No v2 trees in the current Roz universe filter.")
        return
    if not trees:
        st.caption("No typed trees yet. Uncovered cues still list leftover seeds.")

    deliver = (payload.get("deliver_rates") or {}).get("book") or {}
    hits = (payload.get("hit_rates") or {}).get("book") or {}
    st.caption(str(payload.get("caption") or ""))
    window = list(payload.get("window") or [])
    window_text = f"{window[0]}–{window[-1]}" if window else "operational, no gold window"
    st.caption(
        f"Stamp {payload.get('generated_at')} · {payload.get('split')} · "
        f"calendar {payload.get('calendar')} · "
        f"window {window_text}. "
        f"Sector filter {sector_choice or 'all'} does not retune xlk_tech."
    )
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Deliver rate")
        st.caption(scored_rate_caption(deliver.get("n_scoreable"), "promises"))
        st.metric("Book deliver rate", format_rate(deliver.get("deliver_rate")))
        st.caption(
            f"{deliver.get('delivered', 0)} delivered / "
            f"{deliver.get('n_scoreable', 0)} scored"
        )
    with col_b:
        st.subheader("Hit rate")
        st.caption(scored_rate_caption(hits.get("n_scoreable"), "goals"))
        st.metric("Book hit rate", format_rate(hits.get("hit_rate")))
        st.caption(
            f"{hits.get('hit', 0)} hit / {hits.get('n_scoreable', 0)} scored"
        )

    metrics_payload = load_desk_panel_metrics_v2()
    if show_trailing_credibility(book_choice) and metrics_payload:
        st.subheader("Trailing credibility")
        st.caption(
            "Point-in-time expanding rates on management_confidence. "
            "A quarter only sees terminals already cited. Null is an em dash."
        )
        series = [
            row
            for row in (metrics_payload.get("rows") or [])
            if universe is None or str(row.get("ticker") or "").upper() in set(universe)
        ]
        if series:
            st.dataframe(
                [
                    {
                        "company": format_company_label(str(row.get("ticker") or "")),
                        "fiscal_period": row.get("fiscal_period"),
                        "trust": format_rate(row.get("desk_trust")),
                        "trust_n": row.get("desk_trust_n"),
                        "ambition": format_rate(row.get("desk_ambition")),
                        "ambition_n": row.get("desk_ambition_n"),
                    }
                    for row in series
                    if row.get("desk_trust_n") or row.get("desk_ambition_n")
                ],
                hide_index=True,
                use_container_width=True,
            )

    if book_choice == _BOOK_NVDA:
        queue = load_desk_cue_queue_v2()
    elif book_choice == _BOOK_HC:
        queue = load_desk_cue_queue_hc_v2()
    else:
        queue = load_desk_cue_queue_ops_v2()
    latest = latest_scored_fiscal(payload, queue)
    board = clock_board(trees, latest)
    st.subheader("Due and slipped")
    st.caption(
        f"As of {latest or '—'}. Slipped is silent plus a due clock, not missed. "
        "Open trees with no clock are someday wants, not due."
    )
    if board["due"] or board["slipped"]:
        st.dataframe(
            [
                {
                    "bucket": "slipped" if row.get("slipped") else "due",
                    "company": format_company_label(str(row.get("ticker") or "")),
                    "claim": row.get("title"),
                    "kind": row.get("kind"),
                    "clock": row.get("clock") or "—",
                }
                for row in [*board["slipped"], *board["due"]]
            ],
            hide_index=True,
            use_container_width=True,
        )
    if board["open_no_clock"]:
        st.caption(
            f"{len(board['open_no_clock'])} open trees have no clock "
            "(soft someday wants)."
        )
        st.dataframe(
            [
                {
                    "claim": row.get("title"),
                    "kind": row.get("kind"),
                    "state": row.get("state"),
                }
                for row in board["open_no_clock"]
            ],
            hide_index=True,
            use_container_width=True,
        )

    if trees:
        _render_horizon_panel(st, trees)
        _render_quote_table(st, trees)

    missed = list((queue or {}).get("missed") or [])
    if missed:
        st.subheader("Uncovered cues")
        st.caption(
            "Seedable promise/goal cues in novelty_view that are not yet on a "
            "typed tree. Do not auto-seed. Gold 20Q recall stays locked."
        )
        gold = (queue or {}).get("gold") or {}
        st.caption(
            f"Full-history missed {queue.get('n_missed')} / "
            f"{queue.get('n_seedable')} · gold recall {gold.get('recall')}"
        )
        st.dataframe(
            [
                {
                    "company": format_company_label(str(row.get("ticker") or "")),
                    "fiscal_period": row.get("fiscal_period"),
                    "class": row.get("class"),
                    "dimension": row.get("dimension"),
                    "excerpt": row.get("excerpt"),
                }
                for row in missed
            ],
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("Trees")
    for tree in trees:
        kind = str(tree.get("kind") or "")
        outcome = (
            tree.get("delivery") if kind == "promise" else tree.get("goal_outcome")
        )
        title = (
            f"{format_company_label(str(tree.get('ticker') or ''))} "
            f"{tree.get('title')} · {kind} · "
            f"{tree.get('state')} / {outcome}"
        )
        with st.expander(title, expanded=bool(tree.get("slipped"))):
            st.caption(
                f"{tree.get('tree_id')} · {tree.get('beat_id')} · "
                f"clock {tree.get('clock') or '—'} · "
                f"{'open' if tree.get('open') else 'closed'}"
            )
            if tree.get("parent_tree_id"):
                st.caption(
                    f"Evolved from {tree.get('parent_tree_id')}. "
                    "Parent seed cite is kept."
                )
            if tree.get("harden_to_tree_id"):
                st.caption(f"Hardened to promise {tree.get('harden_to_tree_id')}.")
            for row in tree_node_rows(tree):
                label = f"{row['fiscal_period']} · {row['edge']}"
                if row.get("slipped"):
                    label = f"{label} · slipped"
                st.markdown(f"**{label}**")
                if row.get("citation"):
                    st.caption(str(row["citation"]))
                if row.get("excerpt"):
                    st.write(row["excerpt"])
                elif row.get("edge") == "silent":
                    st.info("Silent quarter. No cite on this object.")
            if tree.get("coverage_summary"):
                st.markdown(f"**Coverage.** {tree.get('coverage_summary')}")
            backdrop = attach_metrics_to_backdrop(
                history_backdrop_window(
                    data.company_history(str(tree.get("ticker") or "")),
                    str((tree.get("seed") or {}).get("fiscal_period") or ""),
                    last_cited_fiscal(tree),
                ),
                metrics_by_period(metrics_payload, str(tree.get("ticker") or "")),
            )
            if backdrop:
                st.caption("Historical backdrop — Roz company history around this tree.")
                st.dataframe(
                    [
                        {
                            "fiscal_period": item["fiscal_period"],
                            "role": item["role"] or "—",
                            "narrative_level": item["narrative_level"],
                            "narrative_change": item["narrative_change"],
                            "quant_z": item["quant_z"],
                            "surprise_quant_gap": item["surprise_quant_gap"],
                            "trust": format_rate(item.get("desk_trust")),
                            "trust_n": item.get("desk_trust_n") if item.get("desk_trust_n") else "—",
                            "ambition": format_rate(item.get("desk_ambition")),
                            "ambition_n": item.get("desk_ambition_n")
                            if item.get("desk_ambition_n")
                            else "—",
                        }
                        for item in backdrop
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
