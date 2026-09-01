"""Management transparency ledger. Not desk_trust.

Ignored = a previously mentioned claim they did not take up on a
scored call. Slipped = ignored plus a due clock. Withdrawn =
typed dropped or abandoned (they addressed it by walking away).
Does not invent delivered, hit, or missed. Does not write
production_v1.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.earnings_monitor.dashboard.claims_desk import clock_is_due, fiscal_key

TRANSPARENCY_STAMP = "2026-09-01T15:00:00+00:00"
TRANSPARENCY_FILENAME = "desk_transparency_v2.json"
_V1_STAMP = "2026-08-17T17:28:40+00:00"
_NVDA_STAMP = "2026-08-27T18:02:00+00:00"

ADDRESSED_EDGES = frozenset(
    {
        "restated",
        "evolved",
        "deferred",
        "harden-to-promise",
        "delivered",
        "missed",
        "hit",
        "still-want",
    }
)
WITHDRAWN_EDGES = frozenset({"dropped", "abandoned"})
IGNORED_EDGE = "silent"
LIVE_STATUSES = frozenset({"addressed", "ignored", "slipped"})
LEDGER_STATUSES = frozenset({"addressed", "ignored", "slipped", "withdrawn"})


def normalize_status(value: object) -> str | None:
    raw = str(value or "").strip()
    return raw if raw in LEDGER_STATUSES else None


def classify_node(
    node: Mapping[str, Any],
    *,
    clock: str | None,
) -> str | None:
    edge = str(node.get("edge") or "")
    fiscal = str(node.get("fiscal_period") or "").strip()
    excerpt = str(node.get("excerpt") or "").strip()
    if edge in WITHDRAWN_EDGES:
        return "withdrawn"
    if edge == IGNORED_EDGE or (not excerpt and edge not in ADDRESSED_EDGES):
        if fiscal and clock_is_due(clock, fiscal):
            return "slipped"
        return "ignored"
    if edge in ADDRESSED_EDGES or excerpt:
        return "addressed"
    return None


def _seed_fiscal(tree: Mapping[str, Any]) -> str:
    seed = tree.get("seed") or {}
    return str(seed.get("fiscal_period") or "").strip()


def _tree_clock(tree: Mapping[str, Any]) -> str | None:
    clock = str(tree.get("clock") or "").strip()
    if clock:
        return clock
    seed = tree.get("seed") or {}
    seed_clock = str(seed.get("clock") or "").strip()
    return seed_clock or None


def _typed_nodes(tree: Mapping[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for node in tree.get("nodes") or []:
        if isinstance(node, Mapping):
            found.append(dict(node))
    return found


def typed_events(tree: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One ledger row per typed later node. Seed is the mention, not neglect."""
    clock = _tree_clock(tree)
    ticker = str(tree.get("ticker") or "").upper()
    rows: list[dict[str, Any]] = []
    for node in _typed_nodes(tree):
        status = classify_node(node, clock=clock)
        if status is None:
            continue
        fiscal = str(node.get("fiscal_period") or "").strip()
        if fiscal_key(fiscal)[0] < 0:
            continue
        rows.append(
            {
                "ticker": ticker,
                "tree_id": tree.get("tree_id"),
                "title": tree.get("title"),
                "kind": tree.get("current_kind") or tree.get("kind"),
                "bucket": tree.get("bucket"),
                "fiscal_period": fiscal,
                "status": status,
                "edge": node.get("edge"),
                "clock": node.get("clock") or clock,
                "implicit": False,
                "excerpt": str(node.get("excerpt") or "").strip() or None,
            }
        )
    return rows


def implicit_event(
    tree: Mapping[str, Any],
    fiscal_period: str,
    *,
    addressed: bool,
) -> dict[str, Any] | None:
    """View-only later quarter. Does not write a tree node or a terminal.

    Someday wants with no due clock are not implicit neglect. A scored
    call with no cite becomes slipped only after the clock.
    """
    seed = _seed_fiscal(tree)
    if fiscal_key(fiscal_period)[0] < 0:
        return None
    if fiscal_key(fiscal_period) <= fiscal_key(seed):
        return None
    clock = _tree_clock(tree)
    if addressed:
        status = "addressed"
        edge = "restated"
    elif clock_is_due(clock, fiscal_period):
        status = "slipped"
        edge = IGNORED_EDGE
    else:
        return None
    return {
        "ticker": str(tree.get("ticker") or "").upper(),
        "tree_id": tree.get("tree_id"),
        "title": tree.get("title"),
        "kind": tree.get("current_kind") or tree.get("kind"),
        "bucket": tree.get("bucket"),
        "fiscal_period": fiscal_period,
        "status": status,
        "edge": edge,
        "clock": clock,
        "implicit": True,
        "excerpt": None,
    }


def closed_after(tree: Mapping[str, Any]) -> str | None:
    """First typed terminal fiscal, if the tree has closed."""
    if tree.get("open"):
        return None
    for node in _typed_nodes(tree):
        edge = str(node.get("edge") or "")
        if edge in WITHDRAWN_EDGES or edge in {
            "delivered",
            "missed",
            "hit",
        }:
            fiscal = str(node.get("fiscal_period") or "").strip()
            if fiscal_key(fiscal)[0] >= 0:
                return fiscal
    return None


def merge_events(
    tree: Mapping[str, Any],
    implicit_periods: Sequence[tuple[str, bool]],
) -> list[dict[str, Any]]:
    """Typed nodes win. Implicit fills scored calls with no typed node."""
    typed = typed_events(tree)
    have = {
        str(row.get("fiscal_period") or "")
        for row in typed
        if row.get("fiscal_period")
    }
    stop = closed_after(tree)
    extra: list[dict[str, Any]] = []
    for period, addressed in implicit_periods:
        if period in have:
            continue
        if stop and fiscal_key(period) > fiscal_key(stop):
            continue
        event = implicit_event(tree, period, addressed=addressed)
        if event:
            extra.append(event)
    rows = [*typed, *extra]
    rows.sort(key=lambda row: (fiscal_key(str(row.get("fiscal_period") or "")), str(row.get("tree_id") or "")))
    return rows


def rate_counts(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    addressed = sum(1 for row in events if row.get("status") == "addressed")
    ignored = sum(1 for row in events if row.get("status") == "ignored")
    slipped = sum(1 for row in events if row.get("status") == "slipped")
    withdrawn = sum(1 for row in events if row.get("status") == "withdrawn")
    live = addressed + ignored + slipped
    neglected = ignored + slipped
    return {
        "n_addressed": addressed,
        "n_ignored": ignored,
        "n_slipped": slipped,
        "n_withdrawn": withdrawn,
        "n_live": live,
        "n_neglected": neglected,
        "neglect_rate": (neglected / live) if live else None,
        "slip_rate": (slipped / live) if live else None,
        "withdraw_rate": (withdrawn / (withdrawn + live)) if (withdrawn + live) else None,
    }


def tree_rate_counts(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One vote per tree. A decade of silence after one clock is one slipped tree."""
    trees: dict[str, dict[str, Any]] = {}
    for row in events:
        tree_id = str(row.get("tree_id") or "").strip()
        if not tree_id:
            continue
        bucket = trees.setdefault(
            tree_id,
            {
                "n_addressed": 0,
                "n_ignored": 0,
                "n_slipped": 0,
                "n_withdrawn": 0,
                "due": False,
            },
        )
        status = str(row.get("status") or "")
        if status == "addressed":
            bucket["n_addressed"] += 1
            if clock_is_due(str(row.get("clock") or "") or None, str(row.get("fiscal_period") or "")):
                bucket["due"] = True
        elif status == "ignored":
            bucket["n_ignored"] += 1
        elif status == "slipped":
            bucket["n_slipped"] += 1
            bucket["due"] = True
        elif status == "withdrawn":
            bucket["n_withdrawn"] += 1
    n_trees = len(trees)
    n_slipped = sum(1 for item in trees.values() if item["n_slipped"])
    n_ignored = sum(1 for item in trees.values() if item["n_ignored"])
    n_addressed = sum(1 for item in trees.values() if item["n_addressed"])
    n_withdrawn = sum(1 for item in trees.values() if item["n_withdrawn"])
    n_due = sum(1 for item in trees.values() if item["due"])
    n_neglected = sum(1 for item in trees.values() if item["n_ignored"] or item["n_slipped"])
    return {
        "n_trees": n_trees,
        "n_trees_addressed": n_addressed,
        "n_trees_ignored": n_ignored,
        "n_trees_slipped": n_slipped,
        "n_trees_withdrawn": n_withdrawn,
        "n_trees_due": n_due,
        "n_trees_neglected": n_neglected,
        "tree_neglect_rate": (n_neglected / n_trees) if n_trees else None,
        "tree_slip_rate": (n_slipped / n_due) if n_due else None,
    }


def book_counts(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {**rate_counts(events), **tree_rate_counts(events)}


def filter_events(
    events: Sequence[Mapping[str, Any]],
    *,
    ticker: str | None = None,
    statuses: Sequence[str] | None = None,
    through: str | None = None,
) -> list[dict[str, Any]]:
    want = str(ticker or "").upper() or None
    want_status = {str(item) for item in statuses} if statuses else None
    cap = fiscal_key(str(through or ""))
    found: list[dict[str, Any]] = []
    for row in events:
        if want and str(row.get("ticker") or "").upper() != want:
            continue
        if want_status is not None and str(row.get("status") or "") not in want_status:
            continue
        if cap[0] >= 0 and fiscal_key(str(row.get("fiscal_period") or "")) > cap:
            continue
        found.append(dict(row))
    return found


def expanding_rows(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Point-in-time neglect by ticker × fiscal. A quarter only sees events already dated."""
    tickers = sorted({str(row.get("ticker") or "").upper() for row in events if row.get("ticker")})
    periods = sorted(
        {str(row.get("fiscal_period") or "") for row in events if fiscal_key(str(row.get("fiscal_period") or ""))[0] >= 0},
        key=lambda period: fiscal_key(period),
    )
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        for period in periods:
            here = filter_events(events, ticker=ticker, through=period)
            if not here:
                continue
            counts = rate_counts(here)
            if counts["n_live"] or counts["n_withdrawn"]:
                rows.append({"ticker": ticker, "fiscal_period": period, **counts})
    return rows


def ledger_rows(
    events: Sequence[Mapping[str, Any]],
    *,
    statuses: Sequence[str] = ("ignored", "slipped", "withdrawn"),
) -> list[dict[str, Any]]:
    """The tracking list. Addressed stays in the rate, not the default ledger."""
    return filter_events(events, statuses=statuses)


def collapse_ledger(
    events: Sequence[Mapping[str, Any]],
    *,
    statuses: Sequence[str] = ("ignored", "slipped", "withdrawn"),
) -> list[dict[str, Any]]:
    """Typed rows stay one-to-one. Implicit runs collapse to first/last/n."""
    collapsed: list[dict[str, Any]] = []
    runs: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for row in ledger_rows(events, statuses=statuses):
        if not row.get("implicit"):
            item = dict(row)
            item["n_quarters"] = 1
            item["first_fiscal"] = row.get("fiscal_period")
            item["last_fiscal"] = row.get("fiscal_period")
            collapsed.append(item)
            continue
        key = (str(row.get("tree_id") or ""), str(row.get("status") or ""))
        if key not in runs:
            item = dict(row)
            item["n_quarters"] = 1
            item["first_fiscal"] = row.get("fiscal_period")
            item["last_fiscal"] = row.get("fiscal_period")
            runs[key] = item
            order.append(key)
            continue
        found = runs[key]
        found["n_quarters"] = int(found.get("n_quarters") or 1) + 1
        last = str(row.get("fiscal_period") or "")
        if fiscal_key(last) > fiscal_key(str(found.get("last_fiscal") or "")):
            found["last_fiscal"] = last
            found["fiscal_period"] = last
    collapsed.extend(runs[key] for key in order)
    collapsed.sort(
        key=lambda row: (
            fiscal_key(str(row.get("last_fiscal") or row.get("fiscal_period") or "")),
            str(row.get("tree_id") or ""),
        )
    )
    return collapsed


def neglect_caption(counts: Mapping[str, Any] | None) -> str:
    payload = counts or {}
    live = int(payload.get("n_live") or 0)
    if live <= 0:
        return "No live follow-up quarters yet. Em dash is not a 0% neglect rate."
    neglected = int(payload.get("n_neglected") or 0)
    slipped = int(payload.get("n_slipped") or 0)
    trees_due = int(payload.get("n_trees_due") or 0)
    trees_slipped = int(payload.get("n_trees_slipped") or 0)
    if trees_due > 0:
        return (
            f"{trees_slipped} of {trees_due} dated claims went unanswered after the clock "
            f"({slipped} overdue quarters). Someday wants with no clock are not implicit neglect. "
            "Not desk_trust."
        )
    return (
        f"{neglected} of {live} typed follow-ups left a prior claim unaddressed "
        f"({slipped} slipped). Someday wants with no clock are not implicit neglect. "
        "Not desk_trust."
    )


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


def load_desk_transparency_v2(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    path = _cross_company_json(history_source) / TRANSPARENCY_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    stamp = str(payload.get("generated_at") or "")
    if stamp in {_V1_STAMP, _NVDA_STAMP} or stamp != TRANSPARENCY_STAMP:
        return None
    return payload
