"""Gated new-seed proposals from leftover seedable cue-queue rows.

Writes candidates only. Does not insert trees. Does not call an LLM.
Does not rewrite gold trees. Refuses the 17 Aug stamp.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_cue_queue import V1_STAMP, refuse_forbidden, refuse_stamp  # noqa: E402
from scripts._desk_trees_v2 import FULL_SPLIT, NVDA_STAMP  # noqa: E402

PROPOSALS_NAME = "desk_cue_proposals_v2.json"
FY_RE = re.compile(r"\bFY\d{4}-Q[1-4]\b", re.I)
SLUG_RE = re.compile(r"[^a-z0-9]+")


def proposals_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    return (
        root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / PROPOSALS_NAME
    )


def proposer_gate(queue: Mapping[str, object]) -> tuple[bool, str]:
    gold = queue.get("gold") if isinstance(queue.get("gold"), Mapping) else {}
    if gold.get("recall") != 1.0:
        return False, "gold_recall"
    return True, "ok"


def _slug(text: str) -> str:
    cleaned = SLUG_RE.sub("-", text.lower()).strip("-")
    return cleaned[:40] or "cue"


def propose_clock(excerpt: str) -> str | None:
    match = FY_RE.search(excerpt or "")
    if match:
        return match.group(0).upper()
    return None


def propose_from_missed(row: Mapping[str, object]) -> dict[str, object]:
    excerpt = str(row.get("excerpt") or "").strip()
    kind = str(row.get("class") or "promise")
    fiscal = str(row.get("fiscal_period") or "")
    words = " ".join(excerpt.split()[:8])
    tree_id = f"nvda-proposed-{_slug(fiscal + '-' + words)}"
    return {
        "tree_id": tree_id,
        "kind": kind if kind in {"promise", "goal"} else "promise",
        "fiscal_period": fiscal or None,
        "excerpt": excerpt,
        "clock": propose_clock(excerpt),
        "dimension": row.get("dimension"),
        "status": "candidate",
    }


def build_cue_proposals(
    *,
    book: Mapping[str, object],
    queue: Mapping[str, object],
    now: datetime | None = None,
) -> dict[str, object]:
    refuse_stamp(book.get("generated_at"))
    refuse_forbidden(queue)
    allowed, reason = proposer_gate(queue)
    stamped = now or datetime.now(timezone.utc)
    missed = [row for row in (queue.get("missed") or []) if isinstance(row, Mapping)]
    proposals = [propose_from_missed(row) for row in missed] if allowed else []
    return {
        "generated_at": NVDA_STAMP,
        "split": FULL_SPLIT,
        "written_at": stamped.isoformat(),
        "gate": {"allowed": allowed, "reason": reason},
        "n_proposals": len(proposals),
        "proposals": proposals,
        "note": (
            "Candidates only. Type from novelty_view. "
            "Do not auto-insert. Do not rewrite gold trees."
        ),
    }


def write_cue_proposals(
    *,
    repo_root: Path | str,
    book: Mapping[str, object],
    queue: Mapping[str, object],
    now: datetime | None = None,
) -> dict[str, object]:
    payload = build_cue_proposals(book=book, queue=queue, now=now)
    path = proposals_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    book_path = (
        ROOT
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_v2.json"
    )
    queue_path = (
        ROOT
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_cue_queue_v2.json"
    )
    if not book_path.is_file() or not queue_path.is_file():
        raise SystemExit("desk book or cue queue missing")
    book = json.loads(book_path.read_text(encoding="utf-8"))
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    payload = write_cue_proposals(repo_root=ROOT, book=book, queue=queue)
    print(
        json.dumps(
            {
                "gate": payload["gate"],
                "n_proposals": payload["n_proposals"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
