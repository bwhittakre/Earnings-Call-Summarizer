"""Point-in-time desk_trust / desk_ambition overlay.

Reads desk_trees_v2.json only. Does not rewrite desk_claims_v1.json.
Does not read transcripts_raw. Does not touch production_v1 or the 17 Aug eval.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_claims_v1 import LOCKED_GENERATED_AT as V1_LOCKED  # noqa: E402
from scripts._desk_trees_v2 import (  # noqa: E402
    NVDA_STAMP,
    SPLIT,
    WINDOW,
    fiscal_key,
    v1_flex_still_delivered,
)

CASE_STUDY_ID = "desk_panel_metrics_v2"
DIMENSION = "management_confidence"
PROMISE_SCORED = ("delivered", "missed")
GOAL_SCORED = ("hit", "missed")


def trees_path(root: Path | None = None) -> Path:
    base = root or ROOT
    return (
        base
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_v2.json"
    )


def output_path(root: Path | None = None) -> Path:
    base = root or ROOT
    return (
        base
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_panel_metrics_v2.json"
    )


def overlay_path(root: Path | None = None) -> Path:
    base = root or ROOT
    return (
        base
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_panel_metrics_v2_overlay.json"
    )


def assert_nvda_stamp(generated_at: object) -> None:
    stamp = str(generated_at or "")
    if stamp == V1_LOCKED:
        raise SystemExit(
            "desk_panel_metrics_v2 refuses the 17 Aug tech stamp"
        )
    if stamp != NVDA_STAMP:
        raise SystemExit(
            f"desk_panel_metrics_v2 refuses stamp {stamp!r}; locked {NVDA_STAMP!r}"
        )


def terminal_fiscal(tree: Mapping[str, object]) -> str | None:
    nodes = [node for node in (tree.get("nodes") or []) if isinstance(node, Mapping)]
    if not nodes:
        return None
    last = nodes[-1]
    fiscal = str(last.get("fiscal_period") or "").strip()
    return fiscal or None


def scored_terminal(tree: Mapping[str, object]) -> dict[str, str] | None:
    kind = str(tree.get("kind") or "")
    nodes = [node for node in (tree.get("nodes") or []) if isinstance(node, Mapping)]
    if not nodes:
        return None
    edge = str(nodes[-1].get("edge") or "")
    fiscal = terminal_fiscal(tree)
    if not fiscal or fiscal_key(fiscal)[0] < 0:
        return None
    ticker = str(tree.get("ticker") or "").upper()
    if kind == "promise" and edge in PROMISE_SCORED:
        return {
            "ticker": ticker,
            "fiscal_period": fiscal,
            "kind": "promise",
            "outcome": edge,
        }
    if kind == "goal" and edge in GOAL_SCORED:
        return {
            "ticker": ticker,
            "fiscal_period": fiscal,
            "kind": "goal",
            "outcome": edge,
        }
    return None


def collect_terminals(trees: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for tree in trees:
        if not isinstance(tree, Mapping):
            continue
        item = scored_terminal(tree)
        if item:
            found.append(item)
    return found


def rate_at(
    terminals: Sequence[Mapping[str, str]],
    *,
    ticker: str,
    period: str,
    kind: str,
) -> tuple[float | None, int, int, int]:
    want = str(ticker).upper()
    here = fiscal_key(period)
    scored = [
        item
        for item in terminals
        if item.get("ticker") == want
        and item.get("kind") == kind
        and fiscal_key(str(item.get("fiscal_period") or "")) <= here
        and fiscal_key(str(item.get("fiscal_period") or ""))[0] >= 0
    ]
    if kind == "promise":
        yes = sum(1 for item in scored if item.get("outcome") == "delivered")
        no = sum(1 for item in scored if item.get("outcome") == "missed")
    else:
        yes = sum(1 for item in scored if item.get("outcome") == "hit")
        no = sum(1 for item in scored if item.get("outcome") == "missed")
    n = yes + no
    return ((yes / n) if n else None, n, yes, no)


def build_rows(
    trees: Sequence[Mapping[str, object]],
    periods: Sequence[str] = WINDOW,
) -> list[dict[str, object]]:
    terminals = collect_terminals(trees)
    tickers = sorted({str(tree.get("ticker") or "").upper() for tree in trees if tree.get("ticker")})
    rows: list[dict[str, object]] = []
    for ticker in tickers:
        for period in periods:
            trust, trust_n, delivered, missed = rate_at(
                terminals, ticker=ticker, period=period, kind="promise"
            )
            ambition, ambition_n, hit, goal_missed = rate_at(
                terminals, ticker=ticker, period=period, kind="goal"
            )
            rows.append(
                {
                    "ticker": ticker,
                    "fiscal_period": period,
                    "dimension": DIMENSION,
                    "desk_trust": trust,
                    "desk_trust_n": trust_n,
                    "desk_trust_delivered": delivered,
                    "desk_trust_missed": missed,
                    "desk_ambition": ambition,
                    "desk_ambition_n": ambition_n,
                    "desk_ambition_hit": hit,
                    "desk_ambition_missed": goal_missed,
                }
            )
    return rows


def rates_by_period(rows: Sequence[Mapping[str, object]], ticker: str) -> dict[str, dict[str, object]]:
    want = str(ticker).upper()
    return {
        str(row.get("fiscal_period") or ""): dict(row)
        for row in rows
        if str(row.get("ticker") or "").upper() == want
    }


def overlay_management_confidence(
    panel_rows: Sequence[Mapping[str, object]],
    metric_rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Join metrics onto management_confidence rows only. Other dimensions stay null."""
    lookup = {
        (
            str(row.get("ticker") or "").upper(),
            str(row.get("fiscal_period") or ""),
        ): row
        for row in metric_rows
    }
    out: list[dict[str, object]] = []
    for raw in panel_rows:
        row = dict(raw)
        dim = str(row.get("dimension") or "")
        key = (
            str(row.get("ticker") or "").upper(),
            str(row.get("fiscal_period") or ""),
        )
        metrics = lookup.get(key) if dim == DIMENSION else None
        row["desk_trust"] = None if metrics is None else metrics.get("desk_trust")
        row["desk_trust_n"] = 0 if metrics is None else metrics.get("desk_trust_n")
        row["desk_ambition"] = None if metrics is None else metrics.get("desk_ambition")
        row["desk_ambition_n"] = 0 if metrics is None else metrics.get("desk_ambition_n")
        out.append(row)
    return out


def build_payload(trees_payload: Mapping[str, object]) -> dict[str, object]:
    assert_nvda_stamp(trees_payload.get("generated_at"))
    window = list(trees_payload.get("window") or WINDOW)
    trees = []
    for tree in trees_payload.get("trees") or []:
        if not isinstance(tree, Mapping):
            continue
        seed_fp = str((tree.get("seed") or {}).get("fiscal_period") or "")
        if seed_fp and seed_fp not in window:
            continue
        trees.append(tree)
    rows = build_rows(trees, window)
    last = rows[-1] if rows else {}
    return {
        "generated_at": NVDA_STAMP,
        "case_study_id": CASE_STUDY_ID,
        "split": SPLIT,
        "calendar": "nvidia_fiscal",
        "window": list(trees_payload.get("window") or WINDOW),
        "dimension": DIMENSION,
        "caption": (
            "PIT expanding desk_trust (promises) and desk_ambition (goals) "
            "on management_confidence only. A rate at T uses terminals "
            "whose cite fiscal_period <= T. Unresolved is null. "
            "Not the 17 Aug tech book. production_v1 is not written."
        ),
        "n_rows": len(rows),
        "book_end": {
            "desk_trust": last.get("desk_trust"),
            "desk_trust_n": last.get("desk_trust_n"),
            "desk_ambition": last.get("desk_ambition"),
            "desk_ambition_n": last.get("desk_ambition_n"),
        },
        "rows": rows,
    }


def main() -> int:
    v1_flex_still_delivered()
    path = trees_path()
    if not path.is_file():
        raise SystemExit(f"desk_trees_v2.json missing: {path}")
    trees_payload = json.loads(path.read_text(encoding="utf-8"))
    payload = build_payload(trees_payload)
    out = output_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    overlay = overlay_path()
    overlay.write_text(
        json.dumps(
            {
                "generated_at": NVDA_STAMP,
                "dimension": DIMENSION,
                "rows": [
                    {
                        "ticker": row["ticker"],
                        "fiscal_period": row["fiscal_period"],
                        "dimension": DIMENSION,
                        "desk_trust": row["desk_trust"],
                        "desk_trust_n": row["desk_trust_n"],
                        "desk_ambition": row["desk_ambition"],
                        "desk_ambition_n": row["desk_ambition_n"],
                    }
                    for row in payload["rows"]
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(out)
    print("book_end", payload["book_end"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
