"""Operational claims-desk book for scored tech names.

Not NVIDIA gold. Not the 17 Aug Rank IC book. Does not auto-insert trees.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_trees_v2 import (  # noqa: E402
    NVDA_STAMP,
    V1_LOCKED_GENERATED_AT,
    build_ops_book,
)

OPS_STAMP = "2026-08-31T14:18:00+00:00"
OPS_BOOK_ID = "desk_ops_v2"
OPS_SPLIT = "tech-ops-novelty-present"
TECH_TICKERS: tuple[str, ...] = (
    "AAPL",
    "ACN",
    "ADBE",
    "ADI",
    "ADSK",
    "AMAT",
    "AMD",
    "AMZN",
    "APH",
    "AVGO",
    "CRM",
    "CSCO",
    "CTSH",
    "IBM",
    "INTU",
    "LRCX",
    "MSFT",
    "MU",
    "NVDA",
    "ORCL",
    "TEL",
    "TXN",
    "OPAL",
    "STRW",
)
SEED_FIRST: tuple[str, ...] = (
    "ADBE",
    "ADSK",
    "CRM",
    "IBM",
    "INTU",
    "MSFT",
    "ORCL",
)


def assert_ops_stamp(generated_at: object) -> None:
    stamp = str(generated_at or "")
    if stamp == V1_LOCKED_GENERATED_AT:
        raise SystemExit("ops book refuses the 17 Aug stamp")
    if stamp == NVDA_STAMP:
        raise SystemExit("ops book refuses the NVIDIA gold stamp")
    if stamp != OPS_STAMP:
        raise SystemExit(f"ops book refuses stamp {stamp!r}; need {OPS_STAMP!r}")


def ops_book_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    return (
        root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_ops_v2.json"
    )


def novelty_path_for(ticker: str, repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    return (
        root
        / "Structured Narrative"
        / "output"
        / str(ticker).upper()
        / "json"
        / "novelty_view.json"
    )


def load_novelty_map(
    tickers: Sequence[str],
    repo_root: Path | str | None = None,
) -> dict[str, dict | None]:
    found: dict[str, dict | None] = {}
    for ticker in tickers:
        path = novelty_path_for(ticker, repo_root)
        if not path.is_file():
            found[str(ticker).upper()] = None
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        found[str(ticker).upper()] = payload if isinstance(payload, dict) else None
    return found


def write_ops_book(
    catalog: Sequence[Mapping[str, object]],
    *,
    repo_root: Path | str | None = None,
    verify_excerpts: bool = True,
    overlay: "dict | None" = None,  # from load_overlay("ops")
) -> dict[str, object]:
    assert_ops_stamp(OPS_STAMP)
    from scripts._desk_catalog_overlay import get_overlay_trees, get_overlay_nodes, is_tombstoned

    root = Path(repo_root) if repo_root is not None else ROOT

    # Merge overlay trees (skip tombstoned)
    merged_catalog: list[dict] = list(catalog)
    overlay_nodes: dict[str, list] = {}
    if overlay:
        for ot in get_overlay_trees(overlay):
            if not is_tombstoned(str(ot.get("tree_id") or ""), overlay):
                merged_catalog.append(ot)
        overlay_nodes = get_overlay_nodes(overlay)

    # Append overlay nodes onto existing hand-typed trees
    if overlay_nodes:
        patched: list[dict] = []
        for item in merged_catalog:
            tid = str(item.get("tree_id") or "")
            extra_nodes = overlay_nodes.get(tid)
            if extra_nodes:
                item = dict(item)
                existing = list(item.get("nodes") or [])
                item["nodes"] = existing + [dict(n) for n in extra_nodes]
            patched.append(item)
        merged_catalog = patched

    tickers = sorted(
        {
            str(item.get("ticker") or "").upper()
            for item in merged_catalog
            if str(item.get("ticker") or "").strip()
        }
    )
    novelty_by_ticker = load_novelty_map(tickers, root)
    payload = build_ops_book(
        merged_catalog,
        novelty_by_ticker,
        generated_at=OPS_STAMP,
        verify_excerpts=verify_excerpts,
    )

    # Augment payload with provisional counts from the overlay
    if overlay:
        overlay_tids = {str(t.get("tree_id") or "") for t in get_overlay_trees(overlay)}
        n_provisional = sum(
            1
            for t in payload.get("trees") or []
            if t.get("tree_id") in overlay_tids
            and (t.get("provenance") or {}).get("status") == "provisional"
        )
        n_confirmed_overlay = sum(
            1
            for t in payload.get("trees") or []
            if t.get("tree_id") in overlay_tids
            and (t.get("provenance") or {}).get("status") == "confirmed"
        )
        payload["n_provisional"] = n_provisional
        payload["n_confirmed_overlay"] = n_confirmed_overlay

    path = ops_book_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    from scripts._desk_trees_v2_catalogs import OPS_TREES
    from scripts._desk_catalog_overlay import load_overlay

    overlay = load_overlay("ops")
    payload = write_ops_book(OPS_TREES, repo_root=ROOT, verify_excerpts=True, overlay=overlay)
    print(json.dumps({"n_trees": payload["n_trees"], "tickers": payload["tickers"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
