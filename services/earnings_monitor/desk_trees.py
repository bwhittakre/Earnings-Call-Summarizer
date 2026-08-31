"""Walk open desk-v2 trees after a post_call novelty_view write.

Does not propose new seeds. Does not call an LLM.
Does not read transcripts_raw. Refuses the 17 Aug stamp.

NVIDIA gold stays in desk_trees_v2.json. Tech names walk the ops book.
Healthcare names walk the healthcare book.
Live Roz monitor/worker bind-mount ``./services`` and ``./scripts`` so
this module runs after post_call even when the image bake lags. If those
mounts are missing, refresh on the host with
``python scripts/_desk_ops_scan.py``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger(__name__)

_NVDA_STAMP = "2026-08-27T18:02:00+00:00"
_V1_STAMP = "2026-08-17T17:28:40+00:00"
_OPS_STAMP = "2026-08-31T14:18:00+00:00"
_HC_STAMP = "2026-08-31T14:45:00+00:00"


def trees_book_path(repo_root: Path | str) -> Path:
    return (
        Path(repo_root)
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_v2.json"
    )


def ops_book_path(repo_root: Path | str) -> Path:
    return (
        Path(repo_root)
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_ops_v2.json"
    )


def hc_book_path(repo_root: Path | str) -> Path:
    return (
        Path(repo_root)
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_hc_v2.json"
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


def _walk_book(
    *,
    book_path: Path,
    book: dict,
    ticker: str,
    fiscal_period: str,
    novelty: dict,
    now: datetime | None,
) -> tuple[dict, dict[str, object]]:
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
    return book, {
        "status": "walked",
        "changed": changed,
        "n_trees": len(walked),
        "ticker": str(ticker).upper(),
        "fiscal_period": fiscal_period,
    }


def _write_queue_and_proposals(
    *,
    repo_root: Path | str,
    book: dict,
    novelty: dict,
    trees: list,
    ticker: str,
    fiscal_period: str,
    now: datetime | None,
) -> dict[str, object]:
    from scripts._desk_cue_queue import write_cue_queue
    from scripts._desk_cue_proposals import write_cue_proposals

    written = write_cue_queue(
        repo_root=repo_root,
        book=book,
        novelty=novelty,
        trees=trees,
        latest_quarter=str(fiscal_period),
        now=now,
        ticker=str(ticker).upper(),
    )
    cue_queue: dict[str, object] = {
        "status": "written",
        "n_missed": written.get("n_missed"),
        "latest_n_missed": (written.get("latest") or {}).get("n_missed"),
        "gold_recall": (written.get("gold") or {}).get("recall")
        if isinstance(written.get("gold"), dict)
        else None,
    }
    try:
        proposals = write_cue_proposals(
            repo_root=repo_root,
            book=book,
            queue=written,
            now=now,
            ticker=str(ticker).upper(),
        )
        cue_queue["proposals"] = {
            "status": "written",
            "n_proposals": proposals.get("n_proposals"),
            "gate": proposals.get("gate"),
        }
    except Exception:
        LOG.exception(
            "desk cue proposals failed for %s %s",
            ticker,
            fiscal_period,
        )
        cue_queue["proposals"] = {"status": "error"}
    return cue_queue


def walk_after_novelty_view(
    *,
    repo_root: Path | str,
    ticker: str,
    fiscal_period: str,
    now: datetime | None = None,
) -> dict[str, object]:
    """Walk open trees for this ticker after novelty_view exists."""
    want = str(ticker).upper()
    gold_path = trees_book_path(repo_root)
    gold = load_json(gold_path)
    gold_result: dict[str, object] | None = None
    if gold is None and want == "NVDA":
        return {"status": "skipped", "reason": "no_book"}
    if gold is not None:
        stamp = str(gold.get("generated_at") or "")
        if stamp == _V1_STAMP:
            return {"status": "refused", "reason": "v1_stamp"}
        if want == "NVDA" and stamp != _NVDA_STAMP:
            return {"status": "refused", "reason": "stamp_mismatch", "generated_at": stamp}
    novelty = load_json(novelty_view_path(repo_root, want))
    if novelty is None:
        return {"status": "skipped", "reason": "no_novelty_view"}
    if gold is not None and str(gold.get("generated_at") or "") == _NVDA_STAMP:
        gold, gold_result = _walk_book(
            book_path=gold_path,
            book=gold,
            ticker=want,
            fiscal_period=fiscal_period,
            novelty=novelty,
            now=now,
        )
        LOG.info(
            "desk v2 gold walk %s %s changed=%s",
            want,
            fiscal_period,
            gold_result.get("changed"),
        )

    from scripts._desk_trees_v2_hc import HC_BOOK_ID, HC_TICKERS

    hc_names = {str(ticker).upper() for ticker in HC_TICKERS}
    is_healthcare = want in hc_names

    ops_path = ops_book_path(repo_root)
    ops = load_json(ops_path)
    ops_result: dict[str, object] | None = None
    if ops is not None and not is_healthcare:
        ops_stamp = str(ops.get("generated_at") or "")
        if ops_stamp == _V1_STAMP:
            ops_result = {"status": "refused", "reason": "v1_stamp"}
        elif ops_stamp == _NVDA_STAMP:
            ops_result = {"status": "refused", "reason": "gold_stamp"}
        elif ops_stamp != _OPS_STAMP:
            ops_result = {"status": "refused", "reason": "stamp_mismatch"}
        else:
            ops, ops_result = _walk_book(
                book_path=ops_path,
                book=ops,
                ticker=want,
                fiscal_period=fiscal_period,
                novelty=novelty,
                now=now,
            )
            LOG.info(
                "desk v2 ops walk %s %s changed=%s",
                want,
                fiscal_period,
                ops_result.get("changed"),
            )

    hc_path = hc_book_path(repo_root)
    hc = load_json(hc_path)
    hc_result: dict[str, object] | None = None
    if hc is not None and is_healthcare:
        hc_stamp = str(hc.get("generated_at") or "")
        if hc_stamp == _V1_STAMP:
            hc_result = {"status": "refused", "reason": "v1_stamp"}
        elif hc_stamp == _NVDA_STAMP:
            hc_result = {"status": "refused", "reason": "gold_stamp"}
        elif hc_stamp == _OPS_STAMP:
            hc_result = {"status": "refused", "reason": "ops_stamp"}
        elif hc_stamp != _HC_STAMP:
            hc_result = {"status": "refused", "reason": "stamp_mismatch"}
        else:
            hc, hc_result = _walk_book(
                book_path=hc_path,
                book=hc,
                ticker=want,
                fiscal_period=fiscal_period,
                novelty=novelty,
                now=now,
            )
            LOG.info(
                "desk v2 hc walk %s %s changed=%s",
                want,
                fiscal_period,
                hc_result.get("changed"),
            )

    cue_queue: dict[str, object] | None = None
    try:
        if want == "NVDA" and gold is not None and str(gold.get("generated_at") or "") == _NVDA_STAMP:
            cue_queue = _write_queue_and_proposals(
                repo_root=repo_root,
                book=gold,
                novelty=novelty,
                trees=list(gold.get("trees") or []),
                ticker=want,
                fiscal_period=fiscal_period,
                now=now,
            )
        elif is_healthcare:
            book = hc if hc is not None and str(hc.get("generated_at") or "") == _HC_STAMP else {
                "generated_at": _HC_STAMP,
                "book_id": HC_BOOK_ID,
                "trees": [],
            }
            trees = [
                tree
                for tree in (book.get("trees") or [])
                if str(tree.get("ticker") or "").upper() == want
            ]
            cue_queue = _write_queue_and_proposals(
                repo_root=repo_root,
                book=book,
                novelty=novelty,
                trees=trees,
                ticker=want,
                fiscal_period=fiscal_period,
                now=now,
            )
        else:
            book = ops if ops is not None and str(ops.get("generated_at") or "") == _OPS_STAMP else {
                "generated_at": _OPS_STAMP,
                "book_id": "desk_ops_v2",
                "trees": [],
            }
            trees = [
                tree
                for tree in (book.get("trees") or [])
                if str(tree.get("ticker") or "").upper() == want
            ]
            cue_queue = _write_queue_and_proposals(
                repo_root=repo_root,
                book=book,
                novelty=novelty,
                trees=trees,
                ticker=want,
                fiscal_period=fiscal_period,
                now=now,
            )
    except Exception:
        LOG.exception("desk v2 cue queue failed for %s %s", want, fiscal_period)
        cue_queue = {"status": "error"}

    if want == "NVDA" and gold_result is not None:
        primary = gold_result
        if ops_result is not None:
            primary["ops"] = {
                "status": ops_result.get("status"),
                "changed": ops_result.get("changed"),
                "n_trees": ops_result.get("n_trees"),
            }
    elif is_healthcare:
        primary = hc_result or gold_result
    else:
        primary = ops_result or gold_result
    if primary is None:
        primary = {
            "status": "walked",
            "changed": False,
            "n_trees": 0,
            "ticker": want,
            "fiscal_period": fiscal_period,
        }
    primary["cue_queue"] = cue_queue
    return primary
