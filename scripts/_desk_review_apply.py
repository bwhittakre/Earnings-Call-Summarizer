"""Apply analyst review decisions from desk_review_decisions.json.

Accept  → verdict: insert node into overlay.nodes as confirmed
          seed: promote overlay tree to confirmed (or insert if new)
Reject  → tombstone in overlay; notes appended to seed-prompt negatives
Re-cite → tombstone until re-cited (retract_tree)
Defer   → no action

After applying, rebuilds ops/hc books, regime sidecar, and workshop HTML.

Usage
-----
  python scripts/_desk_review_apply.py            # apply decisions
  python scripts/_desk_review_apply.py --dry-run  # preview without writing
  python scripts/_desk_review_apply.py --stats    # show acceptance rates only
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_catalog_overlay import (  # noqa: E402
    append_node,
    append_tree,
    confirm_tree,
    get_overlay_trees,
    load_overlay,
    retract_tree,
    save_overlay,
    tombstone,
)
from scripts._desk_trees_v2 import infer_materiality, validate_catalog_tree  # noqa: E402
from scripts._desk_trees_v2_ops import write_ops_book  # noqa: E402
from scripts._desk_trees_v2_hc import write_hc_book  # noqa: E402
from scripts._desk_regimes_builder import write_sidecar  # noqa: E402
from scripts._desk_trees_workshop_html import write_workshop_html  # noqa: E402

DATA = ROOT / "data"
DECISIONS_IN = DATA / "desk_review_decisions.json"
NEGATIVES_OUT = DATA / "desk_seed_negatives.json"
SEED_CANDIDATES_IN = DATA / "seed_batch_candidates.json"
TERMINAL_CANDIDATES_IN = DATA / "terminal_score_candidates.json"


# ── loaders ──────────────────────────────────────────────────────────────────

def _load_decisions() -> list[dict]:
    """Read desk_review_decisions.json and return the decisions list."""
    if not DECISIONS_IN.is_file():
        raise SystemExit(f"missing decisions file: {DECISIONS_IN}\nRun `python scripts/_desk_review_sheet.py read` first.")
    payload = json.loads(DECISIONS_IN.read_text(encoding="utf-8"))
    return list(payload.get("decisions") or [])


def _load_book_trees() -> tuple[list[dict], list[dict]]:
    """Return (OPS_TREES, HC_TREES) from their catalog modules."""
    from scripts._desk_trees_v2_catalogs import OPS_TREES  # noqa: E402
    from scripts._desk_trees_v2_hc_catalogs import HC_TREES  # noqa: E402
    return list(OPS_TREES), list(HC_TREES)


def _load_seed_candidates() -> dict[str, list[dict]]:
    """Return {tree_id → candidate} from seed_batch_candidates.json."""
    if not SEED_CANDIDATES_IN.is_file():
        return {}
    payload = json.loads(SEED_CANDIDATES_IN.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for cands in (payload.get("candidates_by_ticker") or {}).values():
        for c in cands or []:
            tid = str(c.get("tree_id") or "")
            if tid:
                out[tid] = c
    return out


def _load_terminal_candidates() -> dict[str, dict]:
    """Return {tree_id → candidate} from terminal_score_candidates.json."""
    if not TERMINAL_CANDIDATES_IN.is_file():
        return {}
    payload = json.loads(TERMINAL_CANDIDATES_IN.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for c in payload.get("candidates") or []:
        tid = str(c.get("tree_id") or "")
        if tid:
            out[tid] = c
    for r in payload.get("needs_review") or []:
        tid = str(r.get("tree_id") or "")
        if tid:
            out.setdefault(tid, r)
    return out


def _find_candidate(tree_id: str, seed_candidates: dict[str, dict]) -> dict | None:
    return seed_candidates.get(tree_id)


def _find_verdict(tree_id: str, terminal_candidates: dict[str, dict]) -> dict | None:
    return terminal_candidates.get(tree_id)


def _overlay_tree_ids(overlay: dict) -> set[str]:
    return {str(t.get("tree_id") or "") for t in get_overlay_trees(overlay)}


def _apply_materiality_override(
    overlay: dict,
    tree_id: str,
    materiality: str,
) -> None:
    """Update seed.materiality on an overlay tree in-place."""
    for tree in overlay.get("trees") or []:
        if str(tree.get("tree_id") or "") == tree_id:
            seed = tree.setdefault("seed", {})
            seed["materiality"] = materiality
            seed["materiality_source"] = "analyst_override"
            break


# ── core logic ────────────────────────────────────────────────────────────────

def apply_decisions(
    decisions: list[dict],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply analyst decisions from desk_review_decisions.json.

    Returns a stats dict with:
      counts_by_decision, counts_by_type, acceptance_rates_by_confidence,
      acceptance_rates_by_bucket, n_negatives_written.
    """
    ops_overlay = load_overlay("ops")
    hc_overlay = load_overlay("hc")
    seed_candidates = _load_seed_candidates()
    terminal_candidates = _load_terminal_candidates()
    ops_ids = _overlay_tree_ids(ops_overlay)
    hc_ids = _overlay_tree_ids(hc_overlay)

    ops_trees, hc_trees = _load_book_trees()
    ops_catalog_ids = {str(t.get("tree_id") or "") for t in ops_trees}
    hc_catalog_ids = {str(t.get("tree_id") or "") for t in hc_trees}

    negatives: dict[str, list[dict]] = defaultdict(list)

    counts_by_decision: Counter[str] = Counter()
    counts_by_type: dict[str, Counter] = {"verdict": Counter(), "seed": Counter()}
    # For acceptance rate stats: {confidence → [accept_bool, ...]}
    accept_by_conf: dict[str, list[bool]] = defaultdict(list)
    accept_by_bucket: dict[str, list[bool]] = defaultdict(list)
    n_skipped_missing_candidate: int = 0

    now_iso = datetime.now(timezone.utc).isoformat()

    for dec in decisions:
        decision = str(dec.get("decision") or "").strip()
        if not decision:
            continue
        row_type = str(dec.get("type") or "")  # "verdict" or "seed"
        tree_id = str(dec.get("tree_id") or "")
        ticker = str(dec.get("ticker") or "").upper()
        notes = str(dec.get("notes") or "").strip()
        mat_override = str(dec.get("materiality") or "").strip()

        counts_by_decision[decision] += 1
        counts_by_type.setdefault(row_type, Counter())[decision] += 1

        # Determine which overlay governs this tree
        if tree_id in ops_ids or tree_id in ops_catalog_ids:
            overlay = ops_overlay
            overlay_book = "ops"
        elif tree_id in hc_ids or tree_id in hc_catalog_ids:
            overlay = hc_overlay
            overlay_book = "hc"
        else:
            # Guess from the candidate's book field, or default ops
            cand = seed_candidates.get(tree_id) or terminal_candidates.get(tree_id) or {}
            book_hint = str(cand.get("book") or "")
            if book_hint == "desk_hc_v2":
                overlay = hc_overlay
                overlay_book = "hc"
            else:
                overlay = ops_overlay
                overlay_book = "ops"

        # Collect stats inputs
        cand = seed_candidates.get(tree_id) or terminal_candidates.get(tree_id) or {}
        conf = str(cand.get("confidence") or "")
        bucket = str(cand.get("bucket") or (cand.get("seed") or {}).get("dimension") or "")
        accepted = decision == "Accept"
        if conf:
            accept_by_conf[conf].append(accepted)
        if bucket:
            accept_by_bucket[bucket].append(accepted)

        # ── apply the decision ──────────────────────────────────────────────

        if decision == "Accept" and row_type == "verdict":
            cand = _find_verdict(tree_id, terminal_candidates)
            if cand:
                node = {
                    "fiscal_period": str(cand.get("proposed_fiscal") or ""),
                    "edge": str(cand.get("proposed_edge") or ""),
                    "delivery_basis": "transcript",
                    "excerpt": str(cand.get("supporting_excerpt") or ""),
                    "confidence": str(cand.get("confidence") or ""),
                    "reasoning": str(cand.get("reasoning") or ""),
                    "accepted_at": now_iso,
                }
                append_node(
                    overlay,
                    tree_id,
                    node,
                    provenance={
                        "source": "analyst_accept",
                        "status": "confirmed",
                        "accepted_at": now_iso,
                        "ticker": ticker,
                    },
                )

        elif decision == "Accept" and row_type == "seed":
            cand = _find_candidate(tree_id, seed_candidates)
            existing_ids = _overlay_tree_ids(ops_overlay) | _overlay_tree_ids(hc_overlay)
            if tree_id in existing_ids:
                # Already in overlay — promote to confirmed
                for ov, _bk in ((ops_overlay, "ops"), (hc_overlay, "hc")):
                    if tree_id in _overlay_tree_ids(ov):
                        confirm_tree(ov, tree_id)
            elif cand is None:
                print(f"[warn] Accept seed {tree_id}: not found in candidates file; skipping", file=sys.stderr)
                n_skipped_missing_candidate += 1
            else:
                seed_obj = dict(cand.get("seed") or {})
                excerpt_val = str(seed_obj.get("excerpt") or "").strip()
                if not excerpt_val:
                    print(f"[warn] Accept seed {tree_id}: candidate has no excerpt; skipping", file=sys.stderr)
                    n_skipped_missing_candidate += 1
                else:
                    # Build a minimal catalog-compatible item from the proposal
                    tree_item: dict[str, Any] = {
                        "tree_id": tree_id,
                        "ticker": ticker,
                        "kind": str(cand.get("kind") or "promise"),
                        "bucket": str(cand.get("bucket") or ""),
                        "title": str(cand.get("title") or ""),
                        "objects": list(cand.get("objects") or []),
                        "seed": seed_obj,
                        "match": cand.get("match"),
                        "nodes": [],
                    }
                    append_tree(
                        overlay,
                        tree_item,
                        provenance={
                            "source": "analyst_accept",
                            "status": "confirmed",
                            "accepted_at": now_iso,
                            "ticker": ticker,
                        },
                    )

        elif decision == "Reject":
            tombstone(
                overlay,
                tree_id,
                reason="rejected",
                notes=notes,
            )
            # If it's a seed, add to negatives for the seed prompt
            if row_type == "seed":
                cand = _find_candidate(tree_id, seed_candidates)
                excerpt = str((cand or {}).get("seed", {}).get("excerpt") or "")
                negatives[ticker].append({
                    "tree_id": tree_id,
                    "title": str((cand or {}).get("title") or ""),
                    "excerpt": excerpt,
                    "reason": notes or "rejected by analyst",
                })

        elif decision == "Re-cite":
            retract_tree(overlay, tree_id)

        elif decision == "Defer":
            pass  # No action

        # ── apply materiality override if provided ──────────────────────────
        if mat_override and decision in ("Accept", "Defer"):
            _apply_materiality_override(overlay, tree_id, mat_override)

        # Re-sync ops/hc references in case overlay was switched mid-loop
        if overlay_book == "ops":
            ops_overlay = overlay
            ops_ids = _overlay_tree_ids(ops_overlay)
        else:
            hc_overlay = overlay
            hc_ids = _overlay_tree_ids(hc_overlay)

    # ── save and rebuild ────────────────────────────────────────────────────
    if not dry_run:
        save_overlay("ops", ops_overlay)
        save_overlay("hc", hc_overlay)

        # Write negatives file
        payload_neg: dict[str, Any] = {
            "note": "Tombstoned seed proposals. Use as negative examples in the seed-extraction prompt.",
            "generated_at": now_iso,
            "negatives_by_ticker": dict(negatives),
        }
        NEGATIVES_OUT.write_text(
            json.dumps(payload_neg, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # Rebuild books
        write_ops_book(ops_trees, overlay=ops_overlay)
        write_hc_book(hc_trees, overlay=hc_overlay)

        # Rebuild regime sidecar and workshop HTML
        try:
            write_sidecar()
        except Exception as exc:
            print(f"[warn] write_sidecar failed: {exc}", file=sys.stderr)
        try:
            write_workshop_html()
        except Exception as exc:
            print(f"[warn] write_workshop_html failed: {exc}", file=sys.stderr)

    # ── stats ───────────────────────────────────────────────────────────────
    def _rates(grouped: dict[str, list[bool]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, flags in sorted(grouped.items()):
            n = len(flags)
            n_accept = sum(flags)
            out[key] = {
                "n": n,
                "n_accept": n_accept,
                "accept_rate": round(n_accept / n, 3) if n else None,
            }
        return out

    return {
        "dry_run": dry_run,
        "n_decisions": sum(counts_by_decision.values()),
        "counts_by_decision": dict(counts_by_decision),
        "counts_by_type": {k: dict(v) for k, v in counts_by_type.items()},
        "acceptance_rates_by_confidence": _rates(accept_by_conf),
        "acceptance_rates_by_bucket": _rates(accept_by_bucket),
        "n_negatives_written": sum(len(v) for v in negatives.values()),
        "n_skipped_missing_candidate": n_skipped_missing_candidate,
    }


# ── CLI ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="preview without writing")
    ap.add_argument("--stats", action="store_true", help="show acceptance rates only")
    args = ap.parse_args(argv)

    decisions = _load_decisions()
    if args.stats:
        # Stats only: no writes
        stats = apply_decisions(decisions, dry_run=True)
        print(json.dumps(stats, indent=2))
        return 0

    stats = apply_decisions(decisions, dry_run=args.dry_run)
    if args.dry_run:
        print(json.dumps({"dry_run": True, **stats}, indent=2))
    else:
        print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
