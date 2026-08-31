"""Write the NVIDIA full-history uncovered-cue queue.

Does not insert trees. Does not call an LLM. Does not read transcripts_raw.
Gold 20Q recall is a locked field on the payload, not overwritten.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_trees_v2 import FULL_SPLIT, NVDA_STAMP, SPLIT, WINDOW  # noqa: E402
from scripts._desk_trees_v2_hc import HC_SPLIT, HC_STAMP  # noqa: E402
from scripts._desk_trees_v2_ops import OPS_SPLIT, OPS_STAMP  # noqa: E402
from scripts._desk_trees_v2_recall import (  # noqa: E402
    novelty_path,
    novelty_periods,
    recall_report,
)

V1_STAMP = "2026-08-17T17:28:40+00:00"
QUEUE_NAME = "desk_cue_queue_v2.json"
FORBIDDEN = ("transcripts_raw", "create_extraction_graph")


def queue_path(
    repo_root: Path | str | None = None,
    *,
    ticker: str | None = None,
) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    folder = root / "Structured Narrative" / "output" / "cross_company" / "json"
    want = str(ticker or "").upper()
    if want and want != "NVDA":
        return folder / f"desk_cue_queue_v2_{want}.json"
    return folder / QUEUE_NAME


def refuse_stamp(stamp: object) -> None:
    text = str(stamp or "")
    if text == V1_STAMP:
        raise SystemExit("cue queue refuses the 17 Aug stamp")
    if text not in {NVDA_STAMP, OPS_STAMP, HC_STAMP}:
        raise SystemExit(
            f"cue queue refuses stamp {text!r}; need gold, ops, or healthcare"
        )


def refuse_forbidden(payload: Mapping[str, object] | None) -> None:
    blob = json.dumps(payload or {})
    for token in FORBIDDEN:
        if token in blob:
            raise SystemExit(f"cue queue refuses {token}")


def _slim_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    slimmed: list[dict[str, object]] = []
    for item in rows:
        slimmed.append(
            {
                "ticker": item.get("ticker"),
                "fiscal_period": item.get("fiscal_period"),
                "class": item.get("class"),
                "dimension": item.get("dimension"),
                "excerpt": item.get("excerpt"),
            }
        )
    return slimmed


def _locked_gold(report: Mapping[str, object]) -> dict[str, object]:
    return {
        "split": SPLIT,
        "window": list(WINDOW),
        "n_seedable": report.get("n_seedable"),
        "n_covered": report.get("n_covered"),
        "n_missed": report.get("n_missed"),
        "recall": report.get("recall"),
    }


def build_cue_queue(
    *,
    book: Mapping[str, object],
    novelty: Mapping[str, object],
    trees: Sequence[Mapping[str, object]],
    latest_quarter: str,
    now: datetime | None = None,
    ticker: str | None = None,
) -> dict[str, object]:
    refuse_stamp(book.get("generated_at"))
    refuse_forbidden(novelty)
    want = str(ticker or "").upper() or None
    stamp = str(book.get("generated_at") or "")
    is_gold = stamp == NVDA_STAMP
    gold = recall_report(novelty, trees, WINDOW, ticker=want) if is_gold else None
    full = recall_report(novelty, trees, novelty_periods(novelty), ticker=want)
    latest = str(latest_quarter or "").strip()
    latest_report = (
        recall_report(novelty, trees, (latest,), ticker=want)
        if latest
        else recall_report(novelty, trees, (), ticker=want)
    )
    stamped = now or datetime.now(timezone.utc)
    return {
        "generated_at": stamp,
        "split": FULL_SPLIT if is_gold else (HC_SPLIT if stamp == HC_STAMP else OPS_SPLIT),
        "ticker": want,
        "latest_quarter": latest or None,
        "written_at": stamped.isoformat(),
        "n_seedable": full.get("n_seedable"),
        "n_covered": full.get("n_covered"),
        "n_missed": full.get("n_missed"),
        "recall": full.get("recall"),
        "missed": _slim_rows(list(full.get("missed") or [])),
        "guidance": _slim_rows(list(full.get("guidance") or [])),
        "rhetoric": _slim_rows(list(full.get("rhetoric") or [])),
        "reject": _slim_rows(list(full.get("reject") or [])),
        "gold": _locked_gold(gold) if gold is not None else None,
        "latest": {
            "fiscal_period": latest or None,
            "n_seedable": latest_report.get("n_seedable"),
            "n_covered": latest_report.get("n_covered"),
            "n_missed": latest_report.get("n_missed"),
            "missed": _slim_rows(list(latest_report.get("missed") or [])),
        },
    }


def write_cue_queue(
    *,
    repo_root: Path | str,
    book: Mapping[str, object],
    novelty: Mapping[str, object],
    trees: Sequence[Mapping[str, object]],
    latest_quarter: str,
    now: datetime | None = None,
    ticker: str | None = None,
) -> dict[str, object]:
    payload = build_cue_queue(
        book=book,
        novelty=novelty,
        trees=trees,
        latest_quarter=latest_quarter,
        now=now,
        ticker=ticker,
    )
    path = queue_path(repo_root, ticker=ticker)
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
    if not book_path.is_file():
        raise SystemExit(f"desk book missing: {book_path}")
    novelty_file = novelty_path()
    if not novelty_file.is_file():
        raise SystemExit(f"NVDA novelty_view missing: {novelty_file}")
    book = json.loads(book_path.read_text(encoding="utf-8"))
    novelty = json.loads(novelty_file.read_text(encoding="utf-8"))
    trees = list(book.get("trees") or [])
    latest = str(book.get("walked_trigger") or "")
    if ":" in latest:
        latest = latest.split(":", 1)[1]
    else:
        periods = novelty_periods(novelty)
        latest = periods[-1] if periods else ""
    payload = write_cue_queue(
        repo_root=ROOT,
        book=book,
        novelty=novelty,
        trees=trees,
        latest_quarter=latest,
    )
    print(
        json.dumps(
            {
                "n_seedable": payload["n_seedable"],
                "n_covered": payload["n_covered"],
                "n_missed": payload["n_missed"],
                "recall": payload["recall"],
                "gold": payload["gold"],
                "latest": {
                    "fiscal_period": payload["latest"]["fiscal_period"],
                    "n_missed": payload["latest"]["n_missed"],
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
