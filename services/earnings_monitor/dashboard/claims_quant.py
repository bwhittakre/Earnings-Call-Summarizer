"""Quant cross-check and expire runner. Not desk_trust.

Reads local narrative_quant.parquet / the sidecar. Does not call Snowflake.
Does not invent delivered / hit / missed. Walk does not write these edges.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts._desk_trees_v2 import (
    DEFAULT_SILENCE_QUARTERS,
    DEFAULT_UNCLOCKED_CAP_QUARTERS,
    EXPIRED_EDGE,
    clock_is_due,
    current_clock,
    fiscal_key,
    last_node_edge,
    normalize_quant,
    shift_fiscal,
)

QUANT_STAMP = "2026-09-01T16:00:00+00:00"
QUANT_FILENAME = "desk_quant_v2.json"
_V1_STAMP = "2026-08-17T17:28:40+00:00"
_NVDA_STAMP = "2026-08-27T18:02:00+00:00"

EXPIRE_CAPTION = (
    "Expiration means it was never followed up in a way we can settle, "
    "so claiming completeness is unfeasible. It is not a miss and not a "
    "withdrawal. An untouched expired claim stays unknown."
)


def compare_actual(
    actual: object,
    op: str | None,
    threshold: object,
) -> bool | None:
    if actual is None or op is None or threshold is None:
        return None
    try:
        number = float(actual)
    except (TypeError, ValueError):
        return None
    if op == "between":
        if not isinstance(threshold, (list, tuple)) or len(threshold) != 2:
            return None
        try:
            low, high = float(threshold[0]), float(threshold[1])
        except (TypeError, ValueError):
            return None
        return low <= number <= high
    try:
        bar = float(threshold)
    except (TypeError, ValueError):
        return None
    if op == "gte":
        return number >= bar
    if op == "lte":
        return number <= bar
    if op == "eq":
        return number == bar
    return None


def tree_clock(tree: Mapping[str, Any]) -> str | None:
    seed = tree.get("seed") or {}
    nodes = [node for node in (tree.get("nodes") or []) if isinstance(node, Mapping)]
    clock = current_clock(seed if isinstance(seed, Mapping) else {}, nodes)
    return clock or (str(tree.get("clock") or "").strip() or None)


def last_cite_fiscal(tree: Mapping[str, Any]) -> str | None:
    seed = str((tree.get("seed") or {}).get("fiscal_period") or "").strip() or None
    last = seed
    for node in tree.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        if str(node.get("edge") or "") in {"silent", EXPIRED_EDGE}:
            continue
        fiscal = str(node.get("fiscal_period") or "").strip()
        if fiscal_key(fiscal)[0] >= 0:
            last = fiscal
    return last


def silent_quarters_since(last_cite: str | None, as_of: str | None) -> int:
    if not last_cite or not as_of:
        return 0
    start = fiscal_key(last_cite)
    end = fiscal_key(as_of)
    if start[0] < 0 or end[0] < 0:
        return 0
    return max(0, (end[0] * 4 + end[1]) - (start[0] * 4 + start[1]))


def first_check_fiscal(tree: Mapping[str, Any]) -> str | None:
    clock = tree_clock(tree)
    if clock:
        return clock
    seed = str((tree.get("seed") or {}).get("fiscal_period") or "")
    quant = tree.get("quant") if isinstance(tree.get("quant"), Mapping) else {}
    try:
        silence = int((quant or {}).get("silence_quarters") or DEFAULT_SILENCE_QUARTERS)
    except (TypeError, ValueError):
        silence = DEFAULT_SILENCE_QUARTERS
    return shift_fiscal(seed, silence)


def stop_fiscal(tree: Mapping[str, Any]) -> str | None:
    typed = str(tree.get("expire") or "").strip() or None
    clock = tree_clock(tree)
    if clock:
        retry = shift_fiscal(clock, DEFAULT_SILENCE_QUARTERS)
        candidates = [item for item in (typed, retry) if item]
        if not candidates:
            return clock
        return min(candidates, key=lambda period: fiscal_key(period))
    quant = tree.get("quant") if isinstance(tree.get("quant"), Mapping) else {}
    try:
        cap_n = int((quant or {}).get("unclocked_cap_quarters") or DEFAULT_UNCLOCKED_CAP_QUARTERS)
    except (TypeError, ValueError):
        cap_n = DEFAULT_UNCLOCKED_CAP_QUARTERS
    seed = str((tree.get("seed") or {}).get("fiscal_period") or "")
    cap = shift_fiscal(seed, cap_n)
    candidates = [item for item in (typed, cap) if item]
    if not candidates:
        return None
    return min(candidates, key=lambda period: fiscal_key(period))


def closed_verdict(tree: Mapping[str, Any]) -> str | None:
    edge = last_node_edge(tree)
    delivery = str(tree.get("delivery") or "")
    goal = str(tree.get("goal_outcome") or "")
    if edge == EXPIRED_EDGE or delivery == EXPIRED_EDGE or goal == EXPIRED_EDGE:
        return "expired"
    if delivery == "delivered" or goal == "hit":
        return "confirmed"
    if delivery == "missed" or goal == "missed":
        return "denied"
    if goal == "dropped" or edge in {"abandoned", "dropped"}:
        return "withdrawn"
    return None


def pick_actual(
    rows: Sequence[Mapping[str, Any]],
    *,
    measure: int | None,
    through: str | None,
) -> dict[str, Any] | None:
    if measure is None or not through:
        return None
    found: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            code = int(row.get("measure"))
        except (TypeError, ValueError):
            continue
        if code != measure:
            continue
        fiscal = str(row.get("fiscal_period") or "")
        if fiscal_key(fiscal)[0] < 0:
            continue
        if fiscal_key(fiscal) > fiscal_key(through):
            continue
        if row.get("actual_value") is None:
            continue
        found.append(row)
    if not found:
        return None
    found.sort(
        key=lambda row: (
            fiscal_key(str(row.get("fiscal_period") or "")),
            1 if str(row.get("period_role") or "") in {"fy1", "reported_q"} else 0,
        )
    )
    best = dict(found[-1])
    return {
        "fiscal_period": best.get("fiscal_period"),
        "actual_value": best.get("actual_value"),
        "measure": best.get("measure"),
        "period_role": best.get("period_role"),
    }


def quant_verdict(
    tree: Mapping[str, Any],
    *,
    as_of: str | None,
    actuals: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """One tree. Clocked checks at/after the clock. Unclocked waits for silence."""
    quant = normalize_quant(tree.get("quant")) if tree.get("quant") else None
    first = first_check_fiscal(tree)
    stop = stop_fiscal(tree)
    closed = closed_verdict(tree)
    payload = {
        "tree_id": tree.get("tree_id"),
        "ticker": str(tree.get("ticker") or "").upper(),
        "title": tree.get("title"),
        "kind": tree.get("current_kind") or tree.get("kind"),
        "clock": tree_clock(tree),
        "expire": tree.get("expire"),
        "last_cite": last_cite_fiscal(tree),
        "silent_quarters": silent_quarters_since(last_cite_fiscal(tree), as_of),
        "first_check": first,
        "stop_fiscal": stop,
        "quant": quant,
        "actual": None,
        "verdict": "pending",
        "next_check": first,
    }
    if closed:
        payload["verdict"] = closed
        payload["next_check"] = None
        return payload
    if quant is None:
        if stop and as_of and clock_is_due(stop, as_of):
            payload["verdict"] = "expired"
            payload["next_check"] = None
        return payload
    if not as_of or fiscal_key(as_of)[0] < 0:
        return payload
    if first and fiscal_key(as_of) < fiscal_key(first):
        return payload
    actual = pick_actual(actuals, measure=quant.get("measure") if quant else None, through=as_of)
    payload["actual"] = actual
    matched = compare_actual(
        None if actual is None else actual.get("actual_value"),
        str(quant.get("op") or "") or None if quant else None,
        None if quant is None else quant.get("threshold"),
    )
    if matched is True:
        payload["verdict"] = "confirmed"
        payload["next_check"] = None
        return payload
    if matched is False:
        payload["verdict"] = "denied"
        payload["next_check"] = None
        return payload
    if stop and clock_is_due(stop, as_of):
        payload["verdict"] = "expired"
        payload["next_check"] = None
        return payload
    payload["verdict"] = "inconclusive"
    payload["next_check"] = shift_fiscal(as_of, DEFAULT_SILENCE_QUARTERS)
    return payload


def apply_node(tree: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Typed close for ops/HC catalogs. Never gold. Never invents a seed."""
    verdict = str(row.get("verdict") or "")
    fiscal = str(row.get("stop_fiscal") or row.get("first_check") or "").strip()
    if fiscal_key(fiscal)[0] < 0:
        return None
    kind = str(tree.get("current_kind") or tree.get("kind") or "promise")
    if verdict == "confirmed":
        edge = "delivered" if kind == "promise" else "hit"
        return {
            "fiscal_period": fiscal,
            "edge": edge,
            "delivery_basis": "quant",
            "excerpt": "Quant confirm against the hand-typed measure binding.",
        }
    if verdict == "denied":
        return {
            "fiscal_period": fiscal,
            "edge": "missed",
            "delivery_basis": "quant",
            "excerpt": "Quant deny against the hand-typed measure binding.",
        }
    if verdict == "expired":
        return {
            "fiscal_period": fiscal,
            "edge": EXPIRED_EDGE,
            "excerpt": "Never followed up in a way we can settle.",
        }
    return None


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


def load_desk_quant_v2(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    path = _cross_company_json(history_source) / QUANT_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    stamp = str(payload.get("generated_at") or "")
    if stamp in {_V1_STAMP, _NVDA_STAMP} or stamp != QUANT_STAMP:
        return None
    return payload
