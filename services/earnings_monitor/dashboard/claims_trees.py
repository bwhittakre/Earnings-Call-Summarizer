"""Read-only Claims Trees page. NVIDIA gold book. No new LLM.

Roz Claims Trees and the standalone workshop HTML are the same
desk. Change both unless the user says the surfaces may differ.
Rebuild with ``python scripts/_desk_trees_workshop_html.py``.
"""
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
    clock_length,
    fiscal_span,
    horizon_event,
    horizon_series,
)
from services.earnings_monitor.dashboard.claims_quotes import (
    filter_quote_rows,
    quote_rows,
)
from services.earnings_monitor.dashboard.claims_transparency import (
    book_counts,
    collapse_ledger,
    load_desk_transparency_v2,
    neglect_caption,
)
from scripts._desk_trees_v2 import (
    BUCKETS,
    bucket_label,
    known_delivered_caption,
    known_delivered_counts,
    normalize_bucket,
)
from services.earnings_monitor.dashboard.claims_quant import (
    EXPIRE_CAPTION,
    load_desk_quant_v2,
)
from services.earnings_monitor.dashboard.company_labels import format_company_label
from services.earnings_monitor.dashboard.data import DashboardData

_BUCKET_FILTER_ALL = "all"
_BUCKET_FILTER_UNBUCKETED = "unbucketed"
_BUCKET_FILTER_CHOICES = (_BUCKET_FILTER_ALL, *BUCKETS, _BUCKET_FILTER_UNBUCKETED)

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


def conversion_from_trees(trees: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Book conversion. Not desk_trust."""
    goals = [tree for tree in trees if str(tree.get("kind") or "") == "goal"]
    became = [
        tree for tree in goals if str(tree.get("goal_outcome") or "") == "became-promise"
    ]
    n_goals = len(goals)
    n_became = len(became)
    return {
        "n_goals": n_goals,
        "n_became_promise": n_became,
        "harden_rate": (n_became / n_goals) if n_goals else None,
    }


def conversion_caption(conversion: Mapping[str, Any] | None) -> str:
    payload = conversion or {}
    n_goals = int(payload.get("n_goals") or 0)
    n_became = int(payload.get("n_became_promise") or 0)
    if n_goals <= 0:
        return "No goals yet. Em dash is not a 0% conversion rate."
    return f"{n_became} of {n_goals} goals became a promise."


def tree_kind_label(tree: Mapping[str, Any]) -> str:
    return str(tree.get("kind_label") or tree.get("kind") or "")


def node_edge_label(row: Mapping[str, Any]) -> str:
    label = str(row.get("edge_label") or "").strip()
    if label:
        return label
    edge = str(row.get("edge") or "")
    if edge == "harden-to-promise":
        return "became a promise"
    return edge


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


def tree_bucket(tree: Mapping[str, Any]) -> str | None:
    return normalize_bucket(tree.get("bucket"))


def bucket_filter_label(choice: str) -> str:
    if choice == _BUCKET_FILTER_ALL:
        return "All"
    if choice == _BUCKET_FILTER_UNBUCKETED:
        return "Unbucketed"
    return bucket_label(choice)


def filter_trees_to_bucket(
    trees: Sequence[Mapping[str, Any]],
    choice: str | None,
) -> list[dict[str, Any]]:
    key = str(choice or _BUCKET_FILTER_ALL)
    if key == _BUCKET_FILTER_ALL:
        return [dict(tree) for tree in trees]
    if key == _BUCKET_FILTER_UNBUCKETED:
        return [dict(tree) for tree in trees if tree_bucket(tree) is None]
    return [dict(tree) for tree in trees if tree_bucket(tree) == key]


def group_trees_by_bucket(
    trees: Sequence[Mapping[str, Any]],
) -> list[tuple[str | None, list[Mapping[str, Any]]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {bucket: [] for bucket in BUCKETS}
    unbucketed: list[Mapping[str, Any]] = []
    for tree in trees:
        key = tree_bucket(tree)
        if key is None or key not in groups:
            unbucketed.append(tree)
        else:
            groups[key].append(tree)
    ordered: list[tuple[str | None, list[Mapping[str, Any]]]] = [
        (bucket, groups[bucket]) for bucket in BUCKETS if groups[bucket]
    ]
    if unbucketed:
        ordered.append((None, unbucketed))
    return ordered


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
            "edge_label": "seed",
        }
    ]
    for node in tree.get("nodes") or []:
        rows.append(
            {
                "fiscal_period": node.get("fiscal_period"),
                "edge": node.get("edge"),
                "edge_label": node.get("edge_label")
                or node_edge_label(node if isinstance(node, Mapping) else {}),
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
    col_h, col_k, col_c, col_bucket = st.columns(4)
    with col_h:
        horizon = st.selectbox("Horizon", list(HORIZON_CHOICES), index=0)
    with col_k:
        kind_choice = st.selectbox("Kind", ("promises", "goals", "both"), index=0)
    with col_c:
        company = st.selectbox("Company", ["all", *tickers], index=0)
    with col_bucket:
        horizon_bucket = st.selectbox(
            "Bucket",
            list(_BUCKET_FILTER_CHOICES),
            index=0,
            format_func=bucket_filter_label,
            key="claims_trees_horizon_bucket",
        )
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
        filter_trees_to_bucket(trees, horizon_bucket),
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


def workshop_horizon_events(trees: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Horizon events at horizon=all, with clock_length for 1Q/2Q/4Q filters."""
    found: list[dict[str, Any]] = []
    for tree in trees:
        if not isinstance(tree, Mapping):
            continue
        event = horizon_event(tree, horizon="all")
        if event is None:
            continue
        item = dict(event)
        item["clock_length"] = clock_length(tree)
        found.append(item)
    return found


def workshop_book_entry(
    name: str,
    payload: Mapping[str, Any] | None,
    queue: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    trees = [dict(tree) for tree in (payload.get("trees") or []) if isinstance(tree, Mapping)]
    return {
        "book_id": name,
        "caption": payload.get("caption"),
        "generated_at": payload.get("generated_at"),
        "split": payload.get("split"),
        "calendar": payload.get("calendar"),
        "window": list(payload.get("window") or []),
        "deliver_rates": payload.get("deliver_rates") or {},
        "hit_rates": payload.get("hit_rates") or {},
        "conversion": payload.get("conversion") or conversion_from_trees(trees),
        "trees": trees,
        "queue": queue,
        "latest": latest_scored_fiscal(payload, queue),
        "horizon_events": workshop_horizon_events(trees),
        "quotes": quote_rows(trees),
        "span": list(book_fiscal_span(trees)),
        "known_delivered": known_delivered_counts(
            trees, latest_scored_fiscal(payload, queue)
        ),
    }


def _load_workshop_regimes(
    history_source: os.PathLike[str] | str | None = None,
) -> dict[str, Any] | None:
    """Load the management-regimes sidecar for the workshop bundle."""
    try:
        from services.earnings_monitor.dashboard.claims_regimes import load_desk_regimes_v1
        return load_desk_regimes_v1(history_source)
    except Exception:
        return None


def _load_seed_candidates(
    repo_root: Path | None = None,
) -> dict[str, Any] | None:
    """Load LLM-proposed seed candidates if present. Gated on file existence."""
    root = repo_root or Path(__file__).resolve().parents[3]
    path = root / "data" / "seed_batch_candidates.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_terminal_candidates(
    repo_root: Path | None = None,
) -> dict[str, Any] | None:
    """Load LLM-proposed terminal candidates if present. Gated on file existence."""
    root = repo_root or Path(__file__).resolve().parents[3]
    path = root / "data" / "terminal_score_candidates.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def workshop_bundle(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Same books and helpers as Roz Claims Trees. No second scoring path."""
    gold = load_desk_trees_v2(history_source)
    ops = load_desk_trees_ops_v2(history_source)
    healthcare = load_desk_trees_hc_v2(history_source)
    entries = [
        workshop_book_entry(_BOOK_NVDA, gold, load_desk_cue_queue_v2(history_source)),
        workshop_book_entry(_BOOK_OPS, ops, load_desk_cue_queue_ops_v2(history_source)),
        workshop_book_entry(_BOOK_HC, healthcare, load_desk_cue_queue_hc_v2(history_source)),
    ]
    books = {str(entry["book_id"]): entry for entry in entries if entry}
    labels: dict[str, str] = {}
    for entry in books.values():
        for tree in entry.get("trees") or []:
            ticker = str(tree.get("ticker") or "").upper()
            if ticker and ticker not in labels:
                labels[ticker] = format_company_label(ticker)
        for row in (entry.get("queue") or {}).get("missed") or []:
            ticker = str(row.get("ticker") or "").upper()
            if ticker and ticker not in labels:
                labels[ticker] = format_company_label(ticker)
    available = [name for name in (_BOOK_NVDA, _BOOK_OPS, _BOOK_HC) if name in books]
    return {
        "surface": "claims_trees",
        "title": "Claims Desk",
        "subtitle": (
            "Workshop for the Roz Claims Trees desk. Same books, rates, "
            "buckets, and edges. Roz sector sidebar is omitted. "
            "Company-history backdrop is Roz-only."
        ),
        "books": books,
        "book_order": available,
        "default_book": suggested_book(None, available),
        "labels": labels,
        "metrics": load_desk_panel_metrics_v2(history_source),
        "buckets": list(BUCKETS),
        "bucket_labels": {key: bucket_label(key) for key in BUCKETS},
        "horizon_choices": list(HORIZON_CHOICES),
        "bucket_filter_choices": list(_BUCKET_FILTER_CHOICES),
        "transparency": load_desk_transparency_v2(history_source),
        "quant": load_desk_quant_v2(history_source),
        "expire_caption": EXPIRE_CAPTION,
        "regimes": _load_workshop_regimes(history_source),
        "seed_candidates": _load_seed_candidates(),
        "terminal_candidates": _load_terminal_candidates(),
    }


def _render_transparency_panel(
    st: Any,
    book_choice: str,
    universe: Sequence[str] | None,
) -> None:
    payload = load_desk_transparency_v2()
    st.subheader("Management transparency")
    if payload is None:
        st.caption(
            "Rebuild the sidecar with python scripts/_desk_transparency_v2.py. "
            "This is not desk_trust."
        )
        return
    block = ((payload.get("books") or {}).get(book_choice) or {})
    counts = dict(block.get("book") or {})
    company_rows = list(block.get("by_company") or [])
    events = list(block.get("events") or [])
    if universe is not None:
        allowed = {str(ticker).upper() for ticker in universe}
        company_rows = [
            row for row in company_rows if str(row.get("ticker") or "").upper() in allowed
        ]
        events = [
            row for row in events if str(row.get("ticker") or "").upper() in allowed
        ]
        counts = book_counts(events)
    st.caption(str(payload.get("caption") or ""))
    st.caption(neglect_caption(counts))
    st.metric("Due-clock slip rate", format_rate(counts.get("tree_slip_rate")))
    st.caption(
        f"{counts.get('n_trees_slipped', 0)} of {counts.get('n_trees_due', 0)} dated trees "
        f"went unanswered · {counts.get('n_slipped', 0)} overdue quarters · "
        f"{counts.get('n_ignored', 0)} typed ignores · "
        f"{counts.get('n_withdrawn', 0)} withdrawn"
    )
    if company_rows:
        st.dataframe(
            [
                {
                    "company": format_company_label(str(row.get("ticker") or "")),
                    "tree_slip": format_rate(row.get("tree_slip_rate")),
                    "slipped_trees": row.get("n_trees_slipped"),
                    "due_trees": row.get("n_trees_due"),
                    "overdue_q": row.get("n_slipped"),
                    "typed_ignore": row.get("n_ignored"),
                    "addressed": row.get("n_addressed"),
                    "withdrawn": row.get("n_withdrawn"),
                }
                for row in company_rows
            ],
            hide_index=True,
            use_container_width=True,
        )
    ledger = collapse_ledger(events)
    st.caption(
        "Ledger: dated claims they let slip, typed silences, or withdrawals. "
        "Implicit slips collapse to first/last quarter. Addressed stays in the rate."
    )
    if ledger:
        st.dataframe(
            [
                {
                    "status": row.get("status"),
                    "company": format_company_label(str(row.get("ticker") or "")),
                    "first": row.get("first_fiscal") or row.get("fiscal_period"),
                    "last": row.get("last_fiscal") or row.get("fiscal_period"),
                    "quarters": row.get("n_quarters") or 1,
                    "claim": row.get("title"),
                    "kind": row.get("kind"),
                    "clock": row.get("clock") or "—",
                    "source": "view" if row.get("implicit") else "typed",
                }
                for row in ledger
            ],
            hide_index=True,
            use_container_width=True,
        )


def _render_quant_panel(st: Any, book_choice: str, latest: str | None) -> None:
    payload = load_desk_quant_v2()
    st.subheader("Quant cross-check")
    st.caption(EXPIRE_CAPTION)
    if payload is None:
        st.caption(
            "Rebuild the sidecar with python scripts/_desk_quant_v2.py. "
            "This is not desk_trust."
        )
        return
    st.caption(str(payload.get("caption") or ""))
    block = ((payload.get("books") or {}).get(book_choice) or {})
    rows = list(block.get("rows") or [])
    st.caption(
        f"As of {block.get('as_of') or latest or '—'}. "
        "Clocked trees check at the clock. Unclocked trees wait four silent "
        "quarters, then stop at expire or seed+8Q."
    )
    if not rows:
        st.caption("No expire or quant bindings on this book.")
        return
    st.dataframe(
        [
            {
                "status": row.get("verdict"),
                "company": format_company_label(str(row.get("ticker") or "")),
                "claim": row.get("title"),
                "clock": row.get("clock") or "—",
                "first_check": row.get("first_check") or "—",
                "stop": row.get("stop_fiscal") or "—",
                "next": row.get("next_check") or "—",
                "actual": (row.get("actual") or {}).get("actual_value")
                if isinstance(row.get("actual"), dict)
                else "—",
            }
            for row in rows
        ],
        hide_index=True,
        use_container_width=True,
    )


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

    if book_choice == _BOOK_NVDA:
        queue = load_desk_cue_queue_v2()
    elif book_choice == _BOOK_HC:
        queue = load_desk_cue_queue_hc_v2()
    else:
        queue = load_desk_cue_queue_ops_v2()
    latest = latest_scored_fiscal(payload, queue)

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

    known = known_delivered_counts(trees, latest)
    st.subheader("Known-delivered")
    st.caption(
        "This is what we know has been delivered. "
        "Aged trees we cannot settle sit in the denominator."
    )
    st.caption(known_delivered_caption(known))
    st.metric("Known-delivered rate", format_rate(known.get("known_delivered_rate")))
    st.caption(
        f"{known.get('n_confirmed', 0)} confirmed / {known.get('n_aged', 0)} aged · "
        f"settled share {format_rate(known.get('settled_share'))} · "
        f"{known.get('n_unknown', 0)} unknown. Not desk_trust."
    )

    conversion = payload.get("conversion") or conversion_from_trees(trees)
    st.subheader("Became a promise")
    st.caption(conversion_caption(conversion))
    st.metric("Conversion rate", format_rate(conversion.get("harden_rate")))
    st.caption(
        f"{conversion.get('n_became_promise', 0)} became a promise / "
        f"{conversion.get('n_goals', 0)} goals. "
        "Not desk_trust. Same tree stays open until the promise closes."
    )

    _render_transparency_panel(st, book_choice, universe)
    _render_quant_panel(st, book_choice, latest)

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

    board = clock_board(trees, latest)
    st.subheader("Due and slipped")
    st.caption(
        f"As of {latest or '—'}. Open clocks on typed trees. "
        "Slipped here is a typed silent plus a due clock, not missed. "
        "The neglect ledger above scores later calls that did not take up a prior claim. "
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
    st.caption(
        "Bucket is the claim theme. Seed dimension is the novelty label "
        "of that sentence."
    )
    list_bucket = st.selectbox(
        "Bucket",
        list(_BUCKET_FILTER_CHOICES),
        index=0,
        format_func=bucket_filter_label,
        key="claims_trees_list_bucket",
    )
    listed = filter_trees_to_bucket(trees, list_bucket)
    st.caption(EXPIRE_CAPTION)
    if not listed:
        st.caption("No trees in this bucket.")
    for bucket_key, group in group_trees_by_bucket(listed):
        st.markdown(f"**{bucket_label(bucket_key)}**")
        for tree in group:
            scoring_kind = str(tree.get("current_kind") or tree.get("kind") or "")
            outcome = (
                tree.get("delivery")
                if scoring_kind == "promise"
                else tree.get("goal_outcome")
            )
            title = (
                f"{format_company_label(str(tree.get('ticker') or ''))} "
                f"{tree.get('title')} · {tree_kind_label(tree)} · "
                f"{tree.get('state')} / {outcome}"
            )
            with st.expander(title, expanded=bool(tree.get("slipped"))):
                st.caption(
                    f"{tree.get('tree_id')} · {tree.get('beat_id')} · "
                    f"{bucket_label(tree_bucket(tree))} · "
                    f"clock {tree.get('clock') or '—'} · "
                    f"{'open' if tree.get('open') else 'closed'}"
                )
                if tree.get("parent_tree_id"):
                    st.caption(
                        f"Evolved from {tree.get('parent_tree_id')}. "
                        "Parent seed cite is kept."
                    )
                if str(tree.get("goal_outcome") or "") == "became-promise":
                    st.caption(
                        "Became a promise. Same tree. Current label is "
                        "promise (was goal) until the promise closes."
                    )
                for row in tree_node_rows(tree):
                    label = f"{row['fiscal_period']} · {node_edge_label(row)}"
                    if row.get("slipped"):
                        label = f"{label} · slipped"
                    st.markdown(f"**{label}**")
                    if row.get("citation"):
                        st.caption(str(row["citation"]))
                    if row.get("excerpt"):
                        st.write(row["excerpt"])
                    elif row.get("edge") == "silent":
                        st.info("Silent quarter. No cite on this object.")
                    elif row.get("edge") == "expired":
                        st.info(
                            "Expired. Completeness is unfeasible. "
                            "Not a miss and not a withdrawal."
                        )
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
                                "trust_n": item.get("desk_trust_n")
                                if item.get("desk_trust_n")
                                else "—",
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
