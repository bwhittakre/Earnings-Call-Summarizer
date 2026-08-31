"""Healthcare claims-desk book for scored large-cap names.

Not NVIDIA gold. Not the tech ops book. Not the 17 Aug Rank IC book.
Does not auto-insert trees. Does not mix desk rates into production_v1.
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
from scripts._desk_trees_v2_ops import OPS_STAMP, load_novelty_map  # noqa: E402

HC_STAMP = "2026-08-31T14:45:00+00:00"
HC_BOOK_ID = "desk_hc_v2"
HC_SPLIT = "hc-ops-novelty-present"
HC_TICKERS: tuple[str, ...] = (
    "LLY",
    "UNH",
    "JNJ",
    "ABBV",
    "MRK",
    "TMO",
    "ABT",
    "DHR",
    "PFE",
    "AMGN",
    "ISRG",
    "SYK",
    "GILD",
    "VRTX",
    "MDT",
    "BMY",
    "REGN",
    "CI",
    "ELV",
    "BSX",
)


def assert_hc_stamp(generated_at: object) -> None:
    stamp = str(generated_at or "")
    if stamp == V1_LOCKED_GENERATED_AT:
        raise SystemExit("healthcare book refuses the 17 Aug stamp")
    if stamp == NVDA_STAMP:
        raise SystemExit("healthcare book refuses the NVIDIA gold stamp")
    if stamp == OPS_STAMP:
        raise SystemExit("healthcare book refuses the tech ops stamp")
    if stamp != HC_STAMP:
        raise SystemExit(f"healthcare book refuses stamp {stamp!r}; need {HC_STAMP!r}")


def hc_book_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    return (
        root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_hc_v2.json"
    )


def write_hc_book(
    catalog: Sequence[Mapping[str, object]],
    *,
    repo_root: Path | str | None = None,
    verify_excerpts: bool = True,
) -> dict[str, object]:
    assert_hc_stamp(HC_STAMP)
    root = Path(repo_root) if repo_root is not None else ROOT
    tickers = sorted(
        {
            str(item.get("ticker") or "").upper()
            for item in catalog
            if str(item.get("ticker") or "").strip()
        }
    )
    novelty_by_ticker = load_novelty_map(tickers, root)
    payload = build_ops_book(
        catalog,
        novelty_by_ticker,
        generated_at=HC_STAMP,
        verify_excerpts=verify_excerpts,
        book_id=HC_BOOK_ID,
        split=HC_SPLIT,
        caption=(
            "Claims desk v2 healthcare book. Not NVIDIA gold. "
            "Not the tech ops book. Not the 17 Aug Rank IC book. "
            "Seed cites start trees; walk does not invent delivered, "
            "hit, or missed."
        ),
    )
    path = hc_book_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    from scripts._desk_trees_v2_hc_catalogs import HC_TREES

    payload = write_hc_book(HC_TREES, repo_root=ROOT, verify_excerpts=True)
    print(json.dumps({"n_trees": payload["n_trees"], "tickers": payload["tickers"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
