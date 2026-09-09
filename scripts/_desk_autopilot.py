"""Desk Autopilot: autonomous seed pull and promise tracking.

Runs the full claims-desk pipeline for one or more tickers:
  1. Walk open trees (existing rule-based scoring)
  2. Build cue queue (missed rows)
  3. Propose seeds via LLM (one Sonnet call per ticker)
  4. Apply gate: verbatim+valid+non-dup → overlay; else recite queue
  5. Rebuild ops/hc books with overlay
  6. Score terminal candidates (budget-capped Sonnet)
  7. Apply verdict gate → overlay; else recite queue
  8. Rebuild regime sidecar + workshop HTML
  9. Write ledger

Kill switch: DESK_AUTOPILOT=0 exits immediately.
Gold tickers (NVDA etc.) are always excluded.

Usage:
  python scripts/_desk_autopilot.py --all [--budget-usd 1.0] [--dry-run]
  python scripts/_desk_autopilot.py --ticker MSFT [--budget-usd 1.0]
  python scripts/_desk_autopilot.py --all --from-existing-candidates [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from scripts._desk_catalog_overlay import (  # noqa: E402
    append_node,
    append_tree,
    is_tombstoned,
    load_overlay,
    overlay_stats,
    save_overlay,
)
from scripts._desk_regimes_builder import write_sidecar  # noqa: E402
from scripts._desk_regimes_stub import ensure_regime_stubs  # noqa: E402
from scripts._desk_retrieval import GOLD_TICKERS  # noqa: E402
from scripts._desk_seed_batch import _load_missed, propose_seeds  # noqa: E402
from scripts._desk_terminal_candidates import score_ticker  # noqa: E402
from scripts._desk_trees_v2 import (  # noqa: E402
    GOAL_EDGES,
    GOAL_TERMINAL,
    MATERIALITY_LEVELS,
    PROMISE_EDGES,
    PROMISE_TERMINAL,
    fiscal_key,
    infer_materiality,
    validate_catalog_tree,
)
from scripts._desk_trees_v2_catalogs import OPS_TREES  # noqa: E402
from scripts._desk_trees_v2_hc import HC_TICKERS, write_hc_book  # noqa: E402
from scripts._desk_trees_v2_hc_catalogs import HC_TREES  # noqa: E402
from scripts._desk_trees_v2_ops import TECH_TICKERS, write_ops_book  # noqa: E402
from scripts._desk_trees_workshop_html import write_workshop_html  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────

OUT_SEEDS = ROOT / "data" / "seed_batch_candidates.json"
OUT_TERMS = ROOT / "data" / "terminal_score_candidates.json"
LEDGER = ROOT / "data" / "desk_autopilot_runs.jsonl"

MODEL = "claude-sonnet-4-5"

_ALL_TERMINAL_EDGES = frozenset(PROMISE_TERMINAL) | frozenset(GOAL_TERMINAL)

# Map desk book name → overlay key
_BOOK_TO_OVERLAY = {
    "desk_ops_v2": "ops",
    "desk_hc_v2": "hc",
}

# ── excerpt normalisation ──────────────────────────────────────────────────────

_WS = re.compile(r"\s+")


def _norm(s: object) -> str:
    return _WS.sub(" ", str(s or "")).strip().lower()


# ── dedup ─────────────────────────────────────────────────────────────────────

def _is_duplicate(
    tree_id: str,
    excerpt: str,
    ticker: str,
    overlay: dict[str, Any],
    hand_typed_trees: list[dict],
) -> bool:
    """Return True if tree_id or excerpt already exists in the overlay or hand-typed catalog.

    - tree_id already in overlay.trees → duplicate.
    - Any overlay tree for this ticker has a seed excerpt that contains or is
      contained by the new excerpt (substring containment, whitespace-normalised,
      lowercased). Mirrors excerpt_covered from _desk_trees_v2_recall.py.
    - Any hand-typed catalog tree for this ticker has the same seed excerpt (same
      substring-containment check).
    """
    # 1. Same tree_id already in overlay
    for t in overlay.get("trees") or []:
        if str(t.get("tree_id") or "") == tree_id:
            return True

    new_norm = _norm(excerpt)
    if len(new_norm) < 24:
        # Too short to dedup by excerpt — only block on tree_id (already checked)
        return False

    ticker_upper = ticker.upper()

    # 2. Same excerpt in another overlay tree for this ticker
    for t in overlay.get("trees") or []:
        if str(t.get("ticker") or "").upper() != ticker_upper:
            continue
        seed = t.get("seed") or {}
        have = _norm(str(seed.get("excerpt") or ""))
        if have and (new_norm in have or have in new_norm):
            return True

    # 3. Same excerpt in a hand-typed catalog tree for this ticker
    for t in hand_typed_trees:
        if str(t.get("ticker") or "").upper() != ticker_upper:
            continue
        seed = t.get("seed") or {}
        have = _norm(str(seed.get("excerpt") or ""))
        if have and (new_norm in have or have in new_norm):
            return True

    return False


# ── validation ────────────────────────────────────────────────────────────────

def _validate_tree_safe(candidate: dict) -> bool:
    """Run validate_catalog_tree, catching SystemExit. Returns True on success."""
    try:
        validate_catalog_tree(candidate)
        return True
    except SystemExit:
        return False


# ── book key lookup ───────────────────────────────────────────────────────────

_OPS_TICKER_SET = frozenset(str(t).upper() for t in TECH_TICKERS)
_HC_TICKER_SET = frozenset(str(t).upper() for t in HC_TICKERS)


def _book_key_for(candidate: dict) -> str:
    """Resolve overlay key ('ops' or 'hc') for a candidate.

    Prefers the 'book' field set by the seed/score pipeline; falls back to
    ticker membership.
    """
    book = str(candidate.get("book") or "")
    if book in _BOOK_TO_OVERLAY:
        return _BOOK_TO_OVERLAY[book]
    ticker = str(candidate.get("ticker") or "").upper()
    if ticker in _OPS_TICKER_SET:
        return "ops"
    if ticker in _HC_TICKER_SET:
        return "hc"
    return "ops"  # default


# ── seed gate ─────────────────────────────────────────────────────────────────

def _apply_seed_gate(
    candidates_by_ticker: dict[str, list[dict]],
    overlays: dict[str, dict[str, Any]],
    hand_typed_by_book: dict[str, list[dict]],
    *,
    from_existing: bool,
    dry_run: bool,
) -> tuple[list[tuple[str, dict, str]], list[tuple[str, dict, str]]]:
    """Apply the seed gate to all proposed seed candidates.

    Returns:
      to_insert: list of (book_key, candidate, status)  — "confirmed" or "provisional"
      recite_queue: list of (book_key, candidate, reason)
    """
    to_insert: list[tuple[str, dict, str]] = []
    recite_queue: list[tuple[str, dict, str]] = []

    for ticker, candidates in candidates_by_ticker.items():
        for cand in candidates:
            book_key = _book_key_for(cand)
            overlay = overlays.get(book_key) or {}
            hand_typed = hand_typed_by_book.get(book_key) or []

            tree_id = str(cand.get("tree_id") or "")
            excerpt = str((cand.get("seed") or {}).get("excerpt") or "")
            confidence = str(cand.get("confidence") or "").lower()

            # Tombstone check (applies in all modes)
            if is_tombstoned(tree_id, overlay):
                recite_queue.append((book_key, cand, "tombstoned"))
                continue

            # Excerpt verified check
            if not cand.get("excerpt_verified"):
                recite_queue.append((book_key, cand, "excerpt_not_verified"))
                continue

            if from_existing:
                # Blanket user decision: verbatim high → confirmed, medium → provisional
                # non-verbatim already filtered above (excerpt_verified == False)
                # Validate structure (same as live path)
                if not _validate_tree_safe(cand):
                    recite_queue.append((book_key, cand, "validation_failed"))
                    continue
                # Still check dedup to avoid double-inserting on re-runs
                if _is_duplicate(tree_id, excerpt, ticker, overlay, hand_typed):
                    recite_queue.append((book_key, cand, "duplicate"))
                    continue
                # Copy materiality from candidate root to seed (build_tree reads from seed.materiality)
                # Set delivery_basis=transcript so verify_tree_against_novelty skips the seed.
                seed_obj = dict(cand.get("seed") or {})
                if not seed_obj.get("materiality") and cand.get("materiality"):
                    seed_obj["materiality"] = cand["materiality"]
                    seed_obj["materiality_rationale"] = cand.get("materiality_rationale") or "from_llm"
                seed_obj.setdefault("delivery_basis", "transcript")
                cand = {**cand, "seed": seed_obj}
                status = "confirmed" if confidence == "high" else "provisional"
                to_insert.append((book_key, cand, status))
            else:
                # Full gate: validate structure
                if not _validate_tree_safe(cand):
                    recite_queue.append((book_key, cand, "validation_failed"))
                    continue

                # Dedup check
                if _is_duplicate(tree_id, excerpt, ticker, overlay, hand_typed):
                    recite_queue.append((book_key, cand, "duplicate"))
                    continue

                # Copy materiality from candidate root to seed (build_tree reads from seed.materiality)
                # Set delivery_basis=transcript so verify_tree_against_novelty skips the seed.
                seed_obj = dict(cand.get("seed") or {})
                if not seed_obj.get("materiality") and cand.get("materiality"):
                    seed_obj["materiality"] = cand["materiality"]
                    seed_obj["materiality_rationale"] = cand.get("materiality_rationale") or "from_llm"
                seed_obj.setdefault("delivery_basis", "transcript")
                cand = {**cand, "seed": seed_obj}
                # Determine status from confidence
                status = "confirmed" if confidence == "high" else "provisional"
                to_insert.append((book_key, cand, status))

    return to_insert, recite_queue


# ── verdict gate ──────────────────────────────────────────────────────────────

def _apply_verdict_gate(
    candidates: list[dict],
    overlays: dict[str, dict[str, Any]],
    *,
    dry_run: bool,
    hand_typed_by_book: dict[str, list[dict]] | None = None,
) -> tuple[list[tuple[str, str, dict, str]], list[tuple[str, dict, str]]]:
    """Apply the verdict gate to terminal-score candidates.

    A verdict passes if:
      - excerpt_verified == True
      - proposed_edge in PROMISE_TERMINAL | GOAL_TERMINAL
      - proposed_edge is valid for the tree's kind (goal vs promise)
      - proposed fiscal_period advances past the last existing node
      - tier <= 3 (free retrieval tier; no LLM budget consumed)
      - tree_id is NOT tombstoned

    Verdict status is always 'provisional'.

    Returns:
      to_insert: list of (book_key, tree_id, node_dict, status)
      recite_queue: list of (book_key, candidate, reason)
    """
    to_insert: list[tuple[str, str, dict, str]] = []
    recite_queue: list[tuple[str, dict, str]] = []

    for cand in candidates:
        book_key = _book_key_for(cand)
        overlay = overlays.get(book_key) or {}
        tree_id = str(cand.get("tree_id") or "")

        proposed_edge = str(cand.get("proposed_edge") or "none")
        proposed_fp = str(cand.get("proposed_fiscal") or "")
        excerpt_verified = cand.get("excerpt_verified")
        retrieval = cand.get("retrieval") or {}
        tier = retrieval.get("tier")

        # Tombstone check
        if is_tombstoned(tree_id, overlay):
            recite_queue.append((book_key, cand, "tombstoned"))
            continue

        # Must be excerpt-verified
        if not excerpt_verified:
            recite_queue.append((book_key, cand, "excerpt_not_verified"))
            continue

        # Must be a terminal edge (broad check first)
        if proposed_edge not in _ALL_TERMINAL_EDGES:
            recite_queue.append((book_key, cand, f"edge_not_terminal:{proposed_edge}"))
            continue

        # Must be free-tier (tier <= 3)
        if tier is None or int(tier) > 3:
            recite_queue.append((book_key, cand, f"tier_too_high:{tier}"))
            continue

        # Look up tree definition for structural validation
        tree_def: dict | None = None
        hand_typed: list[dict] = (hand_typed_by_book or {}).get(book_key) or []
        tree_def = next((t for t in hand_typed if t.get("id") == tree_id), None)
        if tree_def is None:
            overlay_trees = overlay.get("trees") or []
            tree_def = next((t for t in overlay_trees if t.get("id") == tree_id), None)

        # Edge-kind validation: goal trees use GOAL_EDGES, promise trees use PROMISE_EDGES
        if tree_def is not None:
            tree_kind = str(tree_def.get("kind") or "promise")
            valid_edges_for_kind = set(GOAL_EDGES) if tree_kind == "goal" else set(PROMISE_EDGES)
            if proposed_edge not in valid_edges_for_kind:
                recite_queue.append(
                    (book_key, cand, f"edge_invalid_for_{tree_kind}:{proposed_edge}")
                )
                continue

        # Fiscal-period advancement: must be after the seed AND all existing nodes.
        # The seed's fiscal_period is the implicit "previous=0" in the validator.
        if tree_def is not None:
            seed_fp = str((tree_def.get("seed") or {}).get("fiscal_period") or "")
            existing_nodes: list[dict] = list(tree_def.get("nodes") or [])
            existing_nodes.extend((overlay.get("nodes") or {}).get(tree_id) or [])
            fps_to_beat = [fp for fp in [seed_fp] + [n.get("fiscal_period") or "" for n in existing_nodes] if fp]
            if fps_to_beat:
                last_fp = max(fps_to_beat, key=fiscal_key)
                if fiscal_key(proposed_fp) <= fiscal_key(last_fp):
                    recite_queue.append(
                        (book_key, cand, f"fiscal_does_not_advance:{proposed_fp}_after_{last_fp}")
                    )
                    continue

        # Build the node to append
        node: dict = {
            "edge": proposed_edge,
            "fiscal_period": proposed_fp,
            "excerpt": str(cand.get("supporting_excerpt") or ""),
            "dimension": "terminal",
            "status": "verbatim",
            "delivery_basis": "transcript",
        }
        to_insert.append((book_key, tree_id, node, "provisional"))

    return to_insert, recite_queue


# ── book rebuild ──────────────────────────────────────────────────────────────

def _rebuild_books(overlays: dict[str, dict], *, errors: list[str]) -> bool:
    """Write ops and hc books with the current overlays. Logs errors, does not raise."""
    ok = True
    for label, write_fn, catalog, book_key in (
        ("ops", write_ops_book, list(OPS_TREES), "ops"),
        ("hc", write_hc_book, list(HC_TREES), "hc"),
    ):
        try:
            write_fn(catalog, overlay=overlays.get(book_key))
            print(f"  [books] {label} book rebuilt")
        except (Exception, SystemExit) as exc:
            msg = f"book rebuild {label} failed: {exc}"
            print(f"  [WARN] {msg}", file=sys.stderr)
            errors.append(msg)
            ok = False
    return ok


def _rebuild_sidecar(*, errors: list[str]) -> None:
    try:
        path = write_sidecar()
        print(f"  [sidecar] wrote {path}")
    except Exception as exc:
        msg = f"sidecar rebuild failed: {exc}"
        print(f"  [WARN] {msg}", file=sys.stderr)
        errors.append(msg)


def _rebuild_workshop(*, errors: list[str]) -> None:
    try:
        path = write_workshop_html()
        print(f"  [workshop] wrote {path}")
    except Exception as exc:
        msg = f"workshop rebuild failed: {exc}"
        print(f"  [WARN] {msg}", file=sys.stderr)
        errors.append(msg)


# ── ledger ────────────────────────────────────────────────────────────────────

def _write_ledger(entry: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── provenance builder ────────────────────────────────────────────────────────

def _prov(
    status: str,
    *,
    run_id: str,
    confidence: str = "",
    source: str = "autopilot",
) -> dict:
    return {
        "source": source,
        "status": status,
        "confidence": confidence,
        "proposed_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "run_id": run_id,
    }


# ── per-ticker live run ───────────────────────────────────────────────────────

def load_supplemental_cues(
    ticker: str,
    supplemental_cue_file: str | None = None,
) -> list[dict]:
    """Load conference/supplemental cue rows for a ticker.

    Rows come from one of two sources (both merged together if both exist):
      1. data/desk_conf_cue_{TICKER}.json — the persisted conference cue file
         written by _desk_conf_ingest.py.  All events in that file are flattened
         to missed-row dicts with fiscal_period = "CONF-YYYY-MM-DD".
      2. An explicit JSON file path passed via --supplemental-cue-file (the
         ephemeral file that _desk_conf_ingest writes just for this run).

    Returns a list of missed-row dicts ready to be appended to _load_missed().
    """
    from scripts._desk_conf_ingest import _load_conf_cue, _event_to_cue_rows  # noqa: E402

    rows: list[dict] = []

    # Source 1: persisted conference cue file
    payload = _load_conf_cue(ticker)
    for event in (payload.get("events") or []):
        event_with_ticker = dict(event)
        event_with_ticker.setdefault("ticker", ticker.upper())
        rows.extend(_event_to_cue_rows(event_with_ticker))

    # Source 2: one-shot supplemental cue file (from CLI flag)
    if supplemental_cue_file:
        path = Path(supplemental_cue_file)
        if path.is_file():
            extra: Any = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(extra, list):
                rows.extend(extra)
            elif isinstance(extra, dict):
                # Same format as desk_conf_cue: {"ticker":..., "events":[...]}
                for event in (extra.get("events") or []):
                    event.setdefault("ticker", ticker.upper())
                    rows.extend(_event_to_cue_rows(event))

    # Deduplicate by excerpt normalisation (keep first occurrence)
    seen_norms: set[str] = set()
    deduped: list[dict] = []
    for r in rows:
        key = _norm(str(r.get("excerpt") or ""))
        if key not in seen_norms:
            seen_norms.add(key)
            deduped.append(r)

    if deduped:
        print(f"  {ticker.upper()}: {len(deduped)} supplemental cue rows "
              f"loaded (sources: conf_cue + {supplemental_cue_file or 'none'})")
    return deduped


def run_for_ticker(
    ticker: str,
    *,
    budget_usd: float,
    dry_run: bool,
    client: Any,
    plan_only: bool,
    overlays: dict[str, dict],
    hand_typed_by_book: dict[str, list[dict]],
    run_id: str,
    api_key: str | None = None,
    supplemental_cue_file: str | None = None,
) -> dict:
    """Run full live pipeline for one ticker. Returns per-ticker stats dict."""
    stats: dict = {
        "ticker": ticker,
        "seeds_proposed": 0,
        "seeds_inserted_confirmed": 0,
        "seeds_inserted_provisional": 0,
        "seeds_recite_queue": 0,
        "verdicts_proposed": 0,
        "verdicts_inserted": 0,
        "verdicts_recite_queue": 0,
        "errors": [],
    }

    # 1. Ensure regime stub
    try:
        ensure_regime_stubs([ticker], api_key=api_key)
    except Exception as exc:
        stats["errors"].append(f"regime stub: {exc}")

    # 2. Load missed cue-queue rows
    missed = _load_missed(ticker)
    print(f"  {ticker}: {len(missed)} missed cue-queue rows")

    # 2b. Merge in supplemental (conference / AGM) cue rows
    try:
        supp_rows = load_supplemental_cues(ticker, supplemental_cue_file)
        if supp_rows:
            missed = list(missed) + supp_rows
            print(f"  {ticker}: {len(supp_rows)} supplemental rows merged "
                  f"→ {len(missed)} total")
    except Exception as exc:
        stats["errors"].append(f"supplemental_cues: {exc}")

    # 3. Propose seeds
    proposals: list[dict] = []
    if missed and client is not None and not plan_only:
        try:
            proposals = propose_seeds(ticker, missed, client)
        except Exception as exc:
            stats["errors"].append(f"propose_seeds: {exc}")
    elif not missed:
        print(f"  {ticker}: no missed rows — skipping LLM seed proposal")

    # Annotate each proposal with the right book
    book_key = "ops" if ticker.upper() in _OPS_TICKER_SET else "hc"
    book_name = "desk_ops_v2" if book_key == "ops" else "desk_hc_v2"
    for p in proposals:
        p.setdefault("book", book_name)

    stats["seeds_proposed"] = len(proposals)
    print(f"  {ticker}: {len(proposals)} seeds proposed")

    # 4. Apply seed gate
    if proposals:
        to_insert, recite = _apply_seed_gate(
            {ticker: proposals},
            overlays,
            hand_typed_by_book,
            from_existing=False,
            dry_run=dry_run,
        )
        stats["seeds_recite_queue"] = len(recite)
        for bk, cand, status in to_insert:
            if status == "confirmed":
                stats["seeds_inserted_confirmed"] += 1
            else:
                stats["seeds_inserted_provisional"] += 1
            if not dry_run:
                append_tree(
                    overlays[bk],
                    cand,
                    provenance=_prov(
                        status,
                        run_id=run_id,
                        confidence=str(cand.get("confidence") or ""),
                    ),
                )
        if not dry_run:
            save_overlay(book_key, overlays[book_key])
            print(
                f"  {ticker}: overlay saved "
                f"({stats['seeds_inserted_confirmed']} confirmed, "
                f"{stats['seeds_inserted_provisional']} provisional)"
            )

    # 5. Score terminal candidates
    try:
        per_budget = budget_usd
        cands, _ = score_ticker(
            ticker,
            budget_usd=per_budget,
            client=client,
            plan_only=plan_only,
        )
    except Exception as exc:
        stats["errors"].append(f"score_ticker: {exc}")
        cands = []

    stats["verdicts_proposed"] = len(cands)

    # 6. Apply verdict gate
    if cands:
        v_insert, v_recite = _apply_verdict_gate(
            cands, overlays, dry_run=dry_run, hand_typed_by_book=hand_typed_by_book
        )
        stats["verdicts_recite_queue"] = len(v_recite)
        for bk, tree_id, node, vstatus in v_insert:
            stats["verdicts_inserted"] += 1
            if not dry_run:
                append_node(
                    overlays[bk],
                    tree_id,
                    node,
                    provenance=_prov(vstatus, run_id=run_id),
                )
        if not dry_run and v_insert:
            save_overlay("ops", overlays["ops"])
            save_overlay("hc", overlays["hc"])

    return stats


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    # Kill switch
    if os.getenv("DESK_AUTOPILOT", "1") == "0":
        print("DESK_AUTOPILOT=0: kill switch active — exiting.", file=sys.stderr)
        return 0

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--all", dest="all_tickers", action="store_true",
                    help="process all ops+HC tickers")
    ap.add_argument("--ticker", action="append", metavar="TICKER",
                    help="process one or more tickers (repeatable)")
    ap.add_argument("--budget-usd", type=float, default=1.0,
                    help="total Sonnet budget cap for this run (default 1.00)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute gate decisions but do NOT write overlays")
    ap.add_argument("--from-existing-candidates", action="store_true",
                    help="apply gate to seed_batch_candidates.json and "
                         "terminal_score_candidates.json (no new LLM calls)")
    ap.add_argument("--plan", action="store_true",
                    help="pass plan_only=True to score_ticker (no LLM calls)")
    ap.add_argument("--supplemental-cue-file", metavar="PATH",
                    help="path to a JSON file of supplemental cue rows to merge "
                         "(written by _desk_conf_ingest.py; rows are appended to "
                         "the earnings missed list before propose_seeds)")
    args = ap.parse_args(argv)

    from_existing = args.from_existing_candidates
    dry_run = args.dry_run
    plan_only = args.plan
    budget_usd = args.budget_usd

    # Resolve ticker list
    ops_tickers = [t for t in TECH_TICKERS if t not in GOLD_TICKERS]
    hc_tickers = [t for t in HC_TICKERS if t not in GOLD_TICKERS]

    if args.ticker:
        tickers = [t.upper() for t in args.ticker if t.upper() not in GOLD_TICKERS]
    elif args.all_tickers or from_existing:
        tickers = list(dict.fromkeys(list(ops_tickers) + list(hc_tickers)))
    else:
        ap.error("specify --all, --ticker TICKER, or --from-existing-candidates")

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    mode = "from_existing" if from_existing else "live"
    errors: list[str] = []

    print(
        f"Desk Autopilot | run_id={run_id} | mode={mode} | "
        f"{len(tickers)} tickers | budget=${budget_usd:.2f}"
        + (" | DRY RUN" if dry_run else "")
    )

    # Load overlays and hand-typed catalogs
    overlays: dict[str, dict] = {
        "ops": load_overlay("ops"),
        "hc": load_overlay("hc"),
    }
    hand_typed_by_book: dict[str, list[dict]] = {
        "ops": list(OPS_TREES),
        "hc": list(HC_TREES),
    }

    # Ledger entry (will be populated as we go)
    ledger: dict = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": None,
        "mode": mode,
        "tickers": tickers,
        "budget_usd": budget_usd,
        "seeds_proposed": 0,
        "seeds_inserted_confirmed": 0,
        "seeds_inserted_provisional": 0,
        "seeds_recite_queue": 0,
        "verdicts_proposed": 0,
        "verdicts_inserted": 0,
        "verdicts_recite_queue": 0,
        "sonnet_cost_usd": 0.0,
        "errors": [],
    }

    # ── From-existing mode ────────────────────────────────────────────────────
    if from_existing:
        print("\n── Seed gate (from existing candidates) ──")
        if not OUT_SEEDS.is_file():
            print(f"  [WARN] {OUT_SEEDS} not found — skipping seed gate", file=sys.stderr)
        else:
            data = json.loads(OUT_SEEDS.read_text(encoding="utf-8"))
            raw_by_ticker: dict[str, list[dict]] = data.get("candidates_by_ticker") or {}

            # Filter to the requested tickers only
            cbt: dict[str, list[dict]] = {
                t: raw_by_ticker.get(t, []) for t in tickers if t in raw_by_ticker
            }

            to_insert, recite = _apply_seed_gate(
                cbt, overlays, hand_typed_by_book, from_existing=True, dry_run=dry_run
            )
            ledger["seeds_proposed"] = sum(len(v) for v in cbt.values())
            ledger["seeds_recite_queue"] = len(recite)
            for book_key, cand, status in to_insert:
                if status == "confirmed":
                    ledger["seeds_inserted_confirmed"] += 1
                else:
                    ledger["seeds_inserted_provisional"] += 1
                if not dry_run:
                    append_tree(
                        overlays[book_key],
                        cand,
                        provenance=_prov(
                            status,
                            run_id=run_id,
                            confidence=str(cand.get("confidence") or ""),
                        ),
                    )
            if not dry_run:
                save_overlay("ops", overlays["ops"])
                save_overlay("hc", overlays["hc"])

            print(
                f"  Seeds: {ledger['seeds_proposed']} proposed | "
                f"{ledger['seeds_inserted_confirmed']} confirmed | "
                f"{ledger['seeds_inserted_provisional']} provisional | "
                f"{ledger['seeds_recite_queue']} recite_queue"
            )

        print("\n── Verdict gate (from existing terminal candidates) ──")
        if not OUT_TERMS.is_file():
            print(f"  [WARN] {OUT_TERMS} not found — skipping verdict gate", file=sys.stderr)
        else:
            data2 = json.loads(OUT_TERMS.read_text(encoding="utf-8"))
            all_cands: list[dict] = data2.get("candidates") or []
            # Filter to requested tickers
            ticker_set = set(tickers)
            all_cands = [
                c for c in all_cands
                if str(c.get("ticker") or "").upper() in ticker_set
            ]

            v_insert, v_recite = _apply_verdict_gate(
                all_cands, overlays, dry_run=dry_run, hand_typed_by_book=hand_typed_by_book
            )
            ledger["verdicts_proposed"] = len(all_cands)
            ledger["verdicts_recite_queue"] = len(v_recite)
            for book_key, tree_id, node, vstatus in v_insert:
                ledger["verdicts_inserted"] += 1
                if not dry_run:
                    append_node(
                        overlays[book_key],
                        tree_id,
                        node,
                        provenance=_prov(vstatus, run_id=run_id),
                    )
            if not dry_run:
                save_overlay("ops", overlays["ops"])
                save_overlay("hc", overlays["hc"])

            print(
                f"  Verdicts: {ledger['verdicts_proposed']} scored | "
                f"{ledger['verdicts_inserted']} inserted | "
                f"{ledger['verdicts_recite_queue']} recite_queue"
            )

    # ── Live mode ─────────────────────────────────────────────────────────────
    else:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        client = None
        if not plan_only:
            if not api_key:
                print(
                    "Error: ANTHROPIC_API_KEY not set. Add it to .env "
                    "(or use --plan / --from-existing-candidates).",
                    file=sys.stderr,
                )
                return 1
            from src.llm.anthropic_client import AnthropicClient

            client = AnthropicClient(api_key=api_key, model=MODEL, max_retries=1)

        per_ticker_budget = budget_usd / max(1, len(tickers))
        print(f"\nProcessing {len(tickers)} tickers at ${per_ticker_budget:.3f}/ticker")

        for ticker in tickers:
            print(f"\n── {ticker} ──")
            try:
                stats = run_for_ticker(
                    ticker,
                    budget_usd=per_ticker_budget,
                    dry_run=dry_run,
                    client=client,
                    plan_only=plan_only,
                    overlays=overlays,
                    hand_typed_by_book=hand_typed_by_book,
                    run_id=run_id,
                    api_key=api_key,
                    supplemental_cue_file=getattr(args, "supplemental_cue_file", None),
                )
            except Exception as exc:
                msg = f"{ticker}: unhandled error: {exc}"
                print(f"  [ERROR] {msg}", file=sys.stderr)
                errors.append(msg)
                continue

            for k in (
                "seeds_proposed", "seeds_inserted_confirmed", "seeds_inserted_provisional",
                "seeds_recite_queue", "verdicts_proposed", "verdicts_inserted",
                "verdicts_recite_queue",
            ):
                ledger[k] = ledger.get(k, 0) + stats.get(k, 0)
            errors.extend(stats.get("errors") or [])

        # Collect LLM cost
        if client is not None:
            try:
                ledger["sonnet_cost_usd"] = round(
                    getattr(client, "total_cost_usd", 0.0), 6
                )
            except Exception:
                pass

    # ── Post-run: rebuild books + sidecar + workshop ──────────────────────────
    if not dry_run:
        print("\n── Rebuilding books ──")
        _rebuild_books(overlays, errors=errors)

        print("\n── Rebuilding regime sidecar ──")
        _rebuild_sidecar(errors=errors)

        print("\n── Rebuilding workshop HTML ──")
        _rebuild_workshop(errors=errors)

        print("\n── Rebuilding call scorecard + briefs ──")
        try:
            from services.earnings_monitor.scorecard import rebuild_scorecard

            sc = rebuild_scorecard(repo_root=ROOT, rebuild_canvas=False)
            print(
                f"  [scorecard] {sc.get('status')} "
                f"({sc.get('n_entries')} entries, "
                f"briefs={sc.get('briefs_written')})"
            )
            if sc.get("status") != "ok":
                errors.append(f"scorecard: {sc}")
        except Exception as exc:
            msg = f"scorecard rebuild failed: {exc}"
            print(f"  [WARN] {msg}", file=sys.stderr)
            errors.append(msg)

    # ── Overlay stats summary ─────────────────────────────────────────────────
    for book_key in ("ops", "hc"):
        st = overlay_stats(overlays[book_key])
        print(
            f"\nOverlay [{book_key}]: "
            f"{st['n_trees']} trees "
            f"({st['n_confirmed']} confirmed, {st['n_provisional']} provisional) | "
            f"{st['n_total_nodes']} verdict nodes | "
            f"{st['n_tombstones']} tombstones"
        )

    # ── Write ledger ──────────────────────────────────────────────────────────
    ledger["completed_at"] = datetime.now(timezone.utc).isoformat()
    ledger["errors"] = errors
    if not dry_run:
        _write_ledger(ledger)
        print(f"\nLedger → {LEDGER}")

    # Summary
    print(
        f"\n{'[DRY RUN] ' if dry_run else ''}Run complete: "
        f"{ledger['seeds_inserted_confirmed']} seeds confirmed, "
        f"{ledger['seeds_inserted_provisional']} provisional, "
        f"{ledger['seeds_recite_queue']} recite_queue | "
        f"{ledger['verdicts_inserted']} verdicts inserted, "
        f"{ledger['verdicts_recite_queue']} recite_queue"
    )
    if errors:
        print(f"  Errors ({len(errors)}):", file=sys.stderr)
        for e in errors[:10]:
            print(f"    {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
