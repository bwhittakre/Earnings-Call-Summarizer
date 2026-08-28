"""Walk open desk-v2 trees after a post_call novelty_view write.

Does not propose new seeds. Does not call an LLM.
Does not read transcripts_raw. Refuses the 17 Aug stamp.

Live Roz monitor/worker bind-mount ``./services`` and ``./scripts`` so
this module runs after post_call even when the image bake lags. If those
mounts are missing, refresh on the host with
``python scripts/_desk_cue_queue.py``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger(__name__)

_NVDA_STAMP = "2026-08-27T18:02:00+00:00"
_V1_STAMP = "2026-08-17T17:28:40+00:00"


def trees_book_path(repo_root: Path | str) -> Path:
    return (
        Path(repo_root)
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_v2.json"
    )


def novelty_view_path(repo_root: Path | str, ticker: str) -> Path:
    return (
        Path(repo_root)
        / "Structured Narrative"
        / "output"
        / str(ticker).upper()
        / "json"
        / "novelty_view.json"
    )


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def walk_after_novelty_view(
    *,
    repo_root: Path | str,
    ticker: str,
    fiscal_period: str,
    now: datetime | None = None,
) -> dict[str, object]:
    """Walk open trees for this ticker after novelty_view exists.

    No-ops when the book is missing or stamped as v1 / not NVIDIA gold.
    """
    book_path = trees_book_path(repo_root)
    book = load_json(book_path)
    if book is None:
        return {"status": "skipped", "reason": "no_book"}
    stamp = str(book.get("generated_at") or "")
    if stamp == _V1_STAMP:
        return {"status": "refused", "reason": "v1_stamp"}
    if stamp != _NVDA_STAMP:
        return {"status": "refused", "reason": "stamp_mismatch", "generated_at": stamp}
    novelty = load_json(novelty_view_path(repo_root, ticker))
    if novelty is None:
        return {"status": "skipped", "reason": "no_novelty_view"}

    from scripts._desk_trees_v2 import walk_open_trees

    before = list(book.get("trees") or [])
    walked = walk_open_trees(
        before,
        ticker=str(ticker).upper(),
        fiscal_period=str(fiscal_period),
        novelty_view=novelty,
    )
    changed = walked != before
    book["trees"] = walked
    book["walked_at"] = (now or datetime.now(timezone.utc)).isoformat()
    book["walked_trigger"] = f"{str(ticker).upper()}:{fiscal_period}"
    if changed:
        book_path.parent.mkdir(parents=True, exist_ok=True)
        book_path.write_text(json.dumps(book, indent=2), encoding="utf-8")
    LOG.info(
        "desk v2 walk %s %s changed=%s trees=%s",
        ticker,
        fiscal_period,
        changed,
        len(walked),
    )
    cue_queue: dict[str, object] | None = None
    if str(ticker).upper() == "NVDA":
        try:
            from scripts._desk_cue_queue import write_cue_queue

            written = write_cue_queue(
                repo_root=repo_root,
                book=book,
                novelty=novelty,
                trees=walked,
                latest_quarter=str(fiscal_period),
                now=now,
            )
            cue_queue = {
                "status": "written",
                "n_missed": written.get("n_missed"),
                "latest_n_missed": (written.get("latest") or {}).get("n_missed"),
                "gold_recall": (written.get("gold") or {}).get("recall"),
            }
            try:
                from scripts._desk_cue_proposals import write_cue_proposals

                proposals = write_cue_proposals(
                    repo_root=repo_root,
                    book=book,
                    queue=written,
                    now=now,
                )
                cue_queue["proposals"] = {
                    "status": "written",
                    "n_proposals": proposals.get("n_proposals"),
                    "gate": proposals.get("gate"),
                }
            except Exception:
                LOG.exception(
                    "desk v2 cue proposals failed for %s %s",
                    ticker,
                    fiscal_period,
                )
                cue_queue["proposals"] = {"status": "error"}
        except Exception:
            LOG.exception(
                "desk v2 cue queue failed for %s %s",
                ticker,
                fiscal_period,
            )
            cue_queue = {"status": "error"}
    return {
        "status": "walked",
        "changed": changed,
        "n_trees": len(walked),
        "ticker": str(ticker).upper(),
        "fiscal_period": fiscal_period,
        "cue_queue": cue_queue,
    }
