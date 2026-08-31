"""Horizon quarterly and cumulative desk rates. Not locked desk_trust.

Slipped / silent-due counts as a miss for this series only.
Does not write delivered, hit, or missed onto a tree.
Does not write desk_panel_metrics_v2 or production_v1.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from services.earnings_monitor.dashboard.claims_desk import fiscal_key

HORIZON_CHOICES = {"1Q": 1, "2Q": 2, "4Q": 4, "all": None}
TYPED_SUCCESS = {"promise": "delivered", "goal": "hit"}
TYPED_FAIL = "missed"
TYPED_CLOSE = {"delivered", "missed", "abandoned", "hit", "dropped"}


def fiscal_distance(start: str | None, end: str | None) -> int | None:
    begin = fiscal_key(str(start or ""))
    finish = fiscal_key(str(end or ""))
    if begin[0] < 0 or finish[0] < 0:
        return None
    return (finish[0] - begin[0]) * 4 + (finish[1] - begin[1])


def next_fiscal(period: str) -> str | None:
    year, quarter = fiscal_key(period)
    if year < 0:
        return None
    if quarter == 4:
        return f"FY{year + 1}-Q1"
    return f"FY{year}-Q{quarter + 1}"


def fiscal_span(start: str | None, end: str | None) -> list[str]:
    first = str(start or "").strip()
    last = str(end or "").strip()
    if fiscal_key(first)[0] < 0 or fiscal_key(last)[0] < 0:
        return []
    if fiscal_key(first) > fiscal_key(last):
        return []
    found = [first]
    here = first
    while here != last:
        nxt = next_fiscal(here)
        if nxt is None:
            break
        found.append(nxt)
        here = nxt
        if len(found) > 80:
            break
    return found


def clock_length(tree: Mapping[str, Any]) -> int | None:
    seed = tree.get("seed") or {}
    seed_fiscal = str(seed.get("fiscal_period") or "").strip()
    clock = str(tree.get("clock") or seed.get("clock") or "").strip()
    return fiscal_distance(seed_fiscal, clock)


def typed_terminal(tree: Mapping[str, Any]) -> dict[str, str] | None:
    last: dict[str, str] | None = None
    for node in tree.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        edge = str(node.get("edge") or "")
        if edge not in TYPED_CLOSE:
            continue
        fiscal = str(node.get("fiscal_period") or "").strip()
        if not fiscal:
            continue
        last = {"edge": edge, "fiscal_period": fiscal}
    return last


def _horizon_limit(horizon: str | int | None) -> int | None:
    if horizon is None or horizon == "all":
        return None
    if isinstance(horizon, int):
        return horizon
    return HORIZON_CHOICES.get(str(horizon), 1)


def horizon_event(
    tree: Mapping[str, Any],
    *,
    horizon: str | int | None = 1,
) -> dict[str, Any] | None:
    """One event at the clock quarter. Slip miss does not change tree.delivery."""
    kind = str(tree.get("kind") or "")
    if kind not in {"promise", "goal"}:
        return None
    seed = tree.get("seed") or {}
    seed_fiscal = str(seed.get("fiscal_period") or "").strip()
    clock = str(tree.get("clock") or seed.get("clock") or "").strip()
    if not clock or fiscal_key(clock)[0] < 0:
        return None
    if not seed_fiscal or fiscal_key(seed_fiscal)[0] < 0:
        return None
    if fiscal_key(seed_fiscal) > fiscal_key(clock):
        return None
    length = fiscal_distance(seed_fiscal, clock)
    limit = _horizon_limit(horizon)
    if length is None:
        return None
    if limit is not None and length > limit:
        return None
    terminal = typed_terminal(tree)
    success_edge = TYPED_SUCCESS[kind]
    if terminal is not None:
        term_fiscal = terminal["fiscal_period"]
        term_edge = terminal["edge"]
        if term_edge in {"abandoned", "dropped"}:
            return None
        on_time = fiscal_key(term_fiscal) <= fiscal_key(clock)
        if term_edge == success_edge and on_time:
            result = "success"
        elif term_edge == TYPED_FAIL and on_time:
            result = "fail"
        else:
            result = "fail"
    else:
        result = "fail"
    return {
        "ticker": str(tree.get("ticker") or "").upper(),
        "tree_id": tree.get("tree_id"),
        "kind": kind,
        "clock": clock,
        "event_fiscal": clock,
        "result": result,
        "delivery": tree.get("delivery"),
        "goal_outcome": tree.get("goal_outcome"),
        "slipped": bool(tree.get("slipped")),
    }


def collect_horizon_events(
    trees: Sequence[Mapping[str, Any]],
    *,
    horizon: str | int | None = 1,
    ticker: str | None = None,
    window: tuple[str | None, str | None] | None = None,
) -> list[dict[str, Any]]:
    want = str(ticker or "").upper() or None
    start = fiscal_key(str((window or (None, None))[0] or ""))
    end = fiscal_key(str((window or (None, None))[1] or ""))
    found: list[dict[str, Any]] = []
    for tree in trees:
        if not isinstance(tree, Mapping):
            continue
        if want and str(tree.get("ticker") or "").upper() != want:
            continue
        event = horizon_event(tree, horizon=horizon)
        if event is None:
            continue
        here = fiscal_key(str(event.get("event_fiscal") or ""))
        if start[0] >= 0 and here < start:
            continue
        if end[0] >= 0 and here > end:
            continue
        found.append(event)
    return found


def rate_from_events(
    events: Sequence[Mapping[str, Any]],
    *,
    kind: str | None = None,
) -> dict[str, Any]:
    scored = [
        event
        for event in events
        if kind is None or str(event.get("kind") or "") == kind
    ]
    yes = sum(1 for event in scored if event.get("result") == "success")
    no = sum(1 for event in scored if event.get("result") == "fail")
    n = yes + no
    return {
        "rate": (yes / n) if n else None,
        "n": n,
        "yes": yes,
        "no": no,
    }


def horizon_series(
    trees: Sequence[Mapping[str, Any]],
    periods: Sequence[str],
    *,
    horizon: str | int | None = 1,
    ticker: str | None = None,
    kinds: Sequence[str] | None = None,
    window: tuple[str | None, str | None] | None = None,
) -> list[dict[str, Any]]:
    events = collect_horizon_events(
        trees, horizon=horizon, ticker=ticker, window=window
    )
    want_kinds = tuple(kinds) if kinds else None
    rows: list[dict[str, Any]] = []
    for period in periods:
        here = fiscal_key(period)
        if here[0] < 0:
            continue
        quarter = [
            event
            for event in events
            if str(event.get("event_fiscal") or "") == period
            and (want_kinds is None or str(event.get("kind") or "") in want_kinds)
        ]
        running = [
            event
            for event in events
            if fiscal_key(str(event.get("event_fiscal") or "")) <= here
            and (want_kinds is None or str(event.get("kind") or "") in want_kinds)
        ]
        q_rate = rate_from_events(quarter)
        c_rate = rate_from_events(running)
        rows.append(
            {
                "fiscal_period": period,
                "horizon_quarter_rate": q_rate["rate"],
                "horizon_quarter_n": q_rate["n"],
                "horizon_quarter_yes": q_rate["yes"],
                "horizon_quarter_no": q_rate["no"],
                "horizon_cum_rate": c_rate["rate"],
                "horizon_cum_n": c_rate["n"],
                "horizon_cum_yes": c_rate["yes"],
                "horizon_cum_no": c_rate["no"],
            }
        )
    return rows


def build_horizon_chart(rows: Sequence[Mapping[str, Any]]) -> Any | None:
    """Altair chart of quarterly vs cumulative. None when there is no rate."""
    points: list[dict[str, object]] = []
    for row in rows:
        period = str(row.get("fiscal_period") or "")
        if not period:
            continue
        quarterly = row.get("horizon_quarter_rate")
        cumulative = row.get("horizon_cum_rate")
        if quarterly is not None:
            points.append(
                {
                    "fiscal_period": period,
                    "series": "quarterly",
                    "rate": float(quarterly),
                    "n": row.get("horizon_quarter_n"),
                }
            )
        if cumulative is not None:
            points.append(
                {
                    "fiscal_period": period,
                    "series": "cumulative",
                    "rate": float(cumulative),
                    "n": row.get("horizon_cum_n"),
                }
            )
    if not points:
        return None
    try:
        import altair as alt
        import pandas as pd
    except ImportError:
        return None
    frame = pd.DataFrame(points)
    return (
        alt.Chart(frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("fiscal_period:N", sort=list(dict.fromkeys(frame["fiscal_period"])), title="Fiscal"),
            y=alt.Y("rate:Q", title="Rate", scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("series:N", title=None),
            tooltip=[
                alt.Tooltip("fiscal_period:N", title="Fiscal"),
                alt.Tooltip("series:N", title="Series"),
                alt.Tooltip("rate:Q", title="Rate", format=".0%"),
                alt.Tooltip("n:Q", title="n"),
            ],
        )
        .properties(height=280)
    )


def book_fiscal_span(trees: Sequence[Mapping[str, Any]]) -> tuple[str | None, str | None]:
    keys: list[tuple[tuple[int, int], str]] = []
    for tree in trees:
        if not isinstance(tree, Mapping):
            continue
        seed = tree.get("seed") or {}
        for raw in (
            seed.get("fiscal_period"),
            tree.get("clock"),
            seed.get("clock"),
            *(node.get("fiscal_period") for node in (tree.get("nodes") or []) if isinstance(node, Mapping)),
        ):
            text = str(raw or "").strip()
            key = fiscal_key(text)
            if key[0] >= 0:
                keys.append((key, text))
    if not keys:
        return None, None
    keys.sort()
    return keys[0][1], keys[-1][1]
