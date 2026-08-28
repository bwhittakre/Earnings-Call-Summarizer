"""Cue recall over NVIDIA gold novelty_view. No new LLM. No transcripts_raw.

A candidate is a verified excerpt in the locked window that matches a
promise or goal cue. Covered if the excerpt (or a long substring) already
lives on a typed tree. Rhetoric and near-term dollar guidance are tagged
so they do not silently become seeds.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_claims_v1 import all_verified_evidence  # noqa: E402
from scripts._desk_trees_v2 import FULL_SPLIT, NVDA_STAMP, SPLIT, WINDOW, fiscal_key  # noqa: E402
from scripts._desk_trees_v2_nvda import NVDA_TREES  # noqa: E402

PROMISE_CUES = (
    r"\bwe will\b",
    r"\bwe'll\b",
    r"\bwe expect to\b",
    r"\bi expect\b",
    r"\bwe should\b",
    r"\bwe plan to\b",
    r"\bwe(?:'re| are) going to announce\b",
    r"\bwill be available\b",
    r"\bwill launch\b",
    r"\bwill ship\b",
    r"\bwill enable\b",
    r"\bwill deliver\b",
    r"\bwill integrate\b",
    r"\bwill reach\b",
    r"\bwill see a lot of\b",
)
GOAL_CUES = (
    r"\bwe want\b",
    r"\bwe aim\b",
    r"\bwe intend\b",
    r"\bwe are targeting\b",
    r"\bi believe .{0,120}\bwill\b",
    r"\bwe believe .{0,120}\bwill\b",
    r"\bevery single server will\b",
)
REJECT_MARKERS = (
    "supply-constrained environment",
    "supply-constrained outlook",
    "regular capital strategy process",
    "we will of course support the administration",
    "remain roughly at the current percentage",
    "grow to nearly $50 billion",
    "plus or minus 2%",
    "pending acquisition of mellanox",
    "pending acquisition of arm",
    "pegasus will deliver over 320",
    "recognition from the intel",
)
GUIDANCE_CUES = (
    r"\bwe expect (?:revenue|gaap|non-gaap|our gaap|sales|this sequential)\b",
    r"\bwe expect to grow revenue\b",
    r"\bwe expect to return to sequential growth\b",
    r"\bwe expect to continue to grow\b",
    r"\brevenue (?:is expected|to be) \$",
    r"\boutlook\b.{0,40}\$",
    r"\bplus or minus 2%\b",
)
RHETORIC_CUES = (
    r"\bit's going to be\b",
    r"\bis going to be\b",
    r"\bare going to be\b",
    r"\bgoing to continue\b",
    r"\bwe'll (?:take|see|update|go through|make|have)\b",
    r"\bwe will (?:of course|continue to engage|continue to advocate|comply)\b",
)

_PROMISE_RE = re.compile("|".join(PROMISE_CUES), re.I)
_GOAL_RE = re.compile("|".join(GOAL_CUES), re.I)
_GUIDANCE_RE = re.compile("|".join(GUIDANCE_CUES), re.I)
_RHETORIC_RE = re.compile("|".join(RHETORIC_CUES), re.I)


def novelty_path() -> Path:
    return (
        ROOT
        / "Structured Narrative"
        / "output"
        / "NVDA"
        / "json"
        / "novelty_view.json"
    )


def tree_excerpts(trees: Sequence[Mapping[str, object]]) -> list[str]:
    found: list[str] = []
    for tree in trees:
        seed = tree.get("seed") or {}
        excerpt = str(seed.get("excerpt") or "").strip()
        if excerpt:
            found.append(excerpt)
        for node in tree.get("nodes") or []:
            if not isinstance(node, Mapping):
                continue
            text = str(node.get("excerpt") or "").strip()
            if text:
                found.append(text)
    return found


def excerpt_covered(excerpt: str, catalog: Sequence[str]) -> bool:
    want = re.sub(r"\s+", " ", excerpt).strip()
    if len(want) < 24:
        return False
    for have in catalog:
        have_n = re.sub(r"\s+", " ", have).strip()
        if want in have_n or have_n in want:
            return True
        if len(want) > 60 and want[:60] in have_n:
            return True
    return False


def classify(excerpt: str) -> str:
    lowered = excerpt.lower()
    if any(marker in lowered for marker in REJECT_MARKERS):
        return "reject"
    if _GUIDANCE_RE.search(excerpt):
        return "guidance"
    if _RHETORIC_RE.search(excerpt):
        return "rhetoric"
    if _GOAL_RE.search(excerpt) and not _PROMISE_RE.search(excerpt):
        return "goal"
    if _PROMISE_RE.search(excerpt):
        return "promise"
    if _GOAL_RE.search(excerpt):
        return "goal"
    return "other"


def novelty_periods(novelty: Mapping[str, object]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for quarter in novelty.get("quarters") or []:
        if not isinstance(quarter, Mapping):
            continue
        fiscal = str(quarter.get("fiscal_period") or "").strip()
        if not fiscal or fiscal in seen:
            continue
        seen.add(fiscal)
        found.append(fiscal)
    found.sort(key=fiscal_key)
    return found


def collect_candidates(
    novelty: Mapping[str, object],
    periods: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    selected = list(periods) if periods is not None else list(WINDOW)
    allowed = {str(period) for period in selected}
    found: list[dict[str, object]] = []
    for quarter in novelty.get("quarters") or []:
        if not isinstance(quarter, Mapping):
            continue
        fiscal = str(quarter.get("fiscal_period") or "")
        if fiscal not in allowed:
            continue
        for row in all_verified_evidence(quarter):
            excerpt = str(row.get("excerpt") or "").strip()
            if not excerpt:
                continue
            if not (_PROMISE_RE.search(excerpt) or _GOAL_RE.search(excerpt)):
                continue
            found.append(
                {
                    "fiscal_period": fiscal,
                    "dimension": row.get("dimension"),
                    "status": row.get("status"),
                    "excerpt": excerpt,
                    "class": classify(excerpt),
                }
            )
    found.sort(key=lambda item: (fiscal_key(str(item["fiscal_period"])), str(item["class"])))
    return found


def recall_report(
    novelty: Mapping[str, object],
    trees: Sequence[Mapping[str, object]],
    periods: Sequence[str] | None = None,
) -> dict[str, object]:
    catalog = tree_excerpts(trees)
    selected = list(periods) if periods is not None else list(WINDOW)
    candidates = collect_candidates(novelty, selected)
    seedable = [item for item in candidates if item["class"] in {"promise", "goal"}]
    covered = [item for item in seedable if excerpt_covered(str(item["excerpt"]), catalog)]
    missed = [item for item in seedable if item not in covered]
    return {
        "generated_at": NVDA_STAMP,
        "split": SPLIT if tuple(selected) == WINDOW else FULL_SPLIT,
        "n_candidates": len(candidates),
        "n_seedable": len(seedable),
        "n_covered": len(covered),
        "n_missed": len(missed),
        "recall": (len(covered) / len(seedable)) if seedable else None,
        "missed": missed,
        "guidance": [item for item in candidates if item["class"] == "guidance"],
        "rhetoric": [item for item in candidates if item["class"] == "rhetoric"],
        "reject": [item for item in candidates if item["class"] == "reject"],
    }


def main() -> int:
    path = novelty_path()
    if not path.is_file():
        raise SystemExit(f"NVDA novelty_view missing: {path}")
    novelty = json.loads(path.read_text(encoding="utf-8"))
    report = recall_report(novelty, NVDA_TREES)
    print(
        json.dumps(
            {
                "n_candidates": report["n_candidates"],
                "n_seedable": report["n_seedable"],
                "n_covered": report["n_covered"],
                "n_missed": report["n_missed"],
                "recall": report["recall"],
                "missed": [
                    {
                        "fiscal_period": item["fiscal_period"],
                        "class": item["class"],
                        "dimension": item["dimension"],
                        "excerpt": item["excerpt"],
                    }
                    for item in report["missed"]
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
