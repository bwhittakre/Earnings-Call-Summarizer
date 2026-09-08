"""Full-history claims desk onboard for a single ticker.

Runs automatically when a company is first introduced to Roz (via the onboard
hook in services/earnings_monitor/desk_autopilot.py) or manually for bulk backfill.

Pipeline per ticker:
  1. Load all missed cue-queue rows (FY2016-Q1 → anchor period)
  2. Propose seeds via Claude Haiku  [cost-efficient for history]
  3. Apply seed gate → overlay (provisional or confirmed)
  4. Score all open trees via Claude Sonnet
  5. Apply verdict gate → overlay
  6. Auto-detect CEO/CFO regime stub (via _desk_regimes_stub.py)
  7. Checkpoint: write progress so the run is fully resumable

Checkpoint: data/desk_history_progress/{TICKER}.json

Usage:
  python scripts/_desk_history_onboard.py --ticker MSFT
  python scripts/_desk_history_onboard.py --ticker MSFT --dry-run
  python scripts/_desk_history_onboard.py --ticker MSFT --resume
  python scripts/_desk_history_onboard.py --all [--budget-usd 20.0]
"""
from __future__ import annotations

import argparse
import json
import os
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
    load_overlay,
    save_overlay,
)
from scripts._desk_regimes_stub import ensure_regime_stubs  # noqa: E402
from scripts._desk_retrieval import GOLD_TICKERS  # noqa: E402
from scripts._desk_seed_batch import propose_seeds  # noqa: E402
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
from src.llm.anthropic_client import AnthropicClient  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────

SEED_MODEL = "claude-haiku-4-5"      # cheap: history seeding
SCORE_MODEL = "claude-sonnet-4-5"    # precise: terminal scoring

CROSS = ROOT / "Structured Narrative" / "output" / "cross_company" / "json"
CHECKPOINT_DIR = ROOT / "data" / "desk_history_progress"

_ALL_TERMINAL_EDGES = frozenset(PROMISE_TERMINAL) | frozenset(GOAL_TERMINAL)

_OPS_TICKER_SET = frozenset(str(t).upper() for t in TECH_TICKERS)
_HC_TICKER_SET = frozenset(str(t).upper() for t in HC_TICKERS)

# Map book name → overlay key
_BOOK_TO_OVERLAY = {
    "desk_ops_v2": "ops",
    "desk_hc_v2": "hc",
}


# ── checkpoint ────────────────────────────────────────────────────────────────

def _checkpoint_path(ticker: str) -> Path:
    return CHECKPOINT_DIR / f"{ticker.upper()}.json"


def _load_checkpoint(ticker: str) -> dict:
    p = _checkpoint_path(ticker)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_checkpoint(ticker: str, data: dict) -> None:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    _checkpoint_path(ticker).write_text(
        json.dumps({**data, "updated_at": datetime.now(timezone.utc).isoformat()},
                   indent=2),
        encoding="utf-8",
    )


# ── cue-row loading ───────────────────────────────────────────────────────────

def _cue_queue_path(ticker: str) -> Path:
    return CROSS / f"desk_cue_queue_v2_{ticker.upper()}.json"


def _cue_proposals_path(ticker: str) -> Path:
    return CROSS / f"desk_cue_proposals_v2_{ticker.upper()}.json"


def _load_all_cue_rows(ticker: str) -> list[dict]:
    """Load cue rows from cue_queue_v2 (primary) or cue_proposals_v2 (fallback).

    For cold-start (no existing trees): returns ALL rows, not just 'missed'.
    For existing tickers: returns 'missed' rows (already filtered for uncovered).
    Falls back to cue_proposals if the queue file is absent.
    """
    ticker_up = ticker.strip().upper()

    # Primary: cue_queue file
    queue_path = _cue_queue_path(ticker_up)
    if queue_path.is_file():
        try:
            data = json.loads(queue_path.read_text(encoding="utf-8"))
            # 'missed' is the set of uncovered rows — use it directly
            rows = data.get("missed") or []
            if rows:
                return [dict(r) for r in rows if isinstance(r, dict)]
        except Exception:
            pass

    # Fallback: cue_proposals file (SN-generated, pre-filter)
    proposals_path = _cue_proposals_path(ticker_up)
    if proposals_path.is_file():
        try:
            data = json.loads(proposals_path.read_text(encoding="utf-8"))
            proposals = data.get("proposals") or []
            # Remap to the 'missed' row schema: {ticker, fiscal_period, class, dimension, excerpt}
            rows = []
            for p in proposals:
                if not isinstance(p, dict):
                    continue
                rows.append({
                    "ticker": ticker_up,
                    "fiscal_period": str(p.get("fiscal_period") or ""),
                    "class": str(p.get("kind") or "promise"),
                    "dimension": str(p.get("dimension") or ""),
                    "excerpt": str(p.get("excerpt") or ""),
                })
            return rows
        except Exception:
            pass

    return []


# ── book-key lookup ───────────────────────────────────────────────────────────

def _book_key_for(ticker: str) -> str:
    """Return 'ops' or 'hc' based on ticker membership."""
    t = ticker.strip().upper()
    if t in _HC_TICKER_SET:
        return "hc"
    return "ops"


# ── dedup ─────────────────────────────────────────────────────────────────────

import re as _re
_WS = _re.compile(r"\s+")


def _norm(s: object) -> str:
    return _WS.sub(" ", str(s or "")).strip().lower()


def _is_duplicate(tree_id: str, excerpt: str, ticker: str,
                  overlay: dict, hand_typed_trees: list[dict]) -> bool:
    """True if tree_id or excerpt already exists in overlay or hand-typed catalog."""
    if any(str(t.get("tree_id") or "") == tree_id
           for t in (overlay.get("trees") or [])):
        return True

    new_norm = _norm(excerpt)
    if len(new_norm) < 24:
        return False

    ticker_up = ticker.strip().upper()
    for t in (overlay.get("trees") or []):
        if str(t.get("ticker") or "").upper() != ticker_up:
            continue
        have = _norm(str((t.get("seed") or {}).get("excerpt") or ""))
        if have and (new_norm in have or have in new_norm):
            return True

    for t in hand_typed_trees:
        if str(t.get("ticker") or "").upper() != ticker_up:
            continue
        have = _norm(str((t.get("seed") or {}).get("excerpt") or ""))
        if have and (new_norm in have or have in new_norm):
            return True

    return False


def _validate_tree_safe(candidate: dict) -> bool:
    try:
        validate_catalog_tree(candidate)
        return True
    except SystemExit:
        return False


# ── provenance ────────────────────────────────────────────────────────────────

def _prov(status: str, *, run_id: str = "", confidence: str = "") -> dict:
    return {
        "source": "history_onboard",
        "status": status,
        "run_id": run_id,
        "confidence": confidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ── seed gate ─────────────────────────────────────────────────────────────────

def _apply_seed_gate(
    proposals: list[dict],
    overlay: dict,
    hand_typed_trees: list[dict],
    *,
    dry_run: bool = False,
    run_id: str = "",
) -> tuple[list[tuple[str, dict, str]], list[dict]]:
    """Gate proposals → (to_insert[(bk, cand, status)], recite_queue)."""
    to_insert: list[tuple[str, dict, str]] = []
    recite: list[dict] = []

    for cand in proposals:
        ticker = str(cand.get("ticker") or "")
        bk = _book_key_for(ticker)
        seed = cand.get("seed") or {}
        excerpt = str(seed.get("excerpt") or "")
        tree_id = str(cand.get("tree_id") or "")

        # Reject: no tree_id or excerpt
        if not tree_id or not excerpt:
            recite.append({**cand, "_recite_reason": "missing_tree_id_or_excerpt"})
            continue

        # Reject: duplicate
        if _is_duplicate(tree_id, excerpt, ticker, overlay, hand_typed_trees):
            recite.append({**cand, "_recite_reason": "duplicate"})
            continue

        # Reject: invalid schema
        if not _validate_tree_safe(cand):
            recite.append({**cand, "_recite_reason": "schema_invalid"})
            continue

        # Determine insertion status
        conf = str(cand.get("confidence") or "")
        verified = bool(cand.get("excerpt_verified"))
        status = "confirmed" if (verified and conf == "high") else "provisional"

        to_insert.append((bk, cand, status))

    return to_insert, recite


# ── verdict gate (thin wrapper — reuse autopilot logic) ──────────────────────

def _apply_verdict_gate(
    candidates: list[dict],
    overlays: dict[str, dict],
    hand_typed_by_book: dict[str, list[dict]],
    *,
    dry_run: bool = False,
) -> tuple[list[tuple[str, str, dict, str]], list[dict]]:
    """Minimally gate terminal scoring candidates: dedup by tree_id only."""
    to_insert: list[tuple[str, str, dict, str]] = []
    recite: list[dict] = []

    for cand in candidates:
        ticker = str(cand.get("ticker") or "")
        bk = _book_key_for(ticker)
        tree_id = str(cand.get("tree_id") or "")
        node = cand.get("node") or {}
        edge = str(node.get("edge") or "")

        if edge not in _ALL_TERMINAL_EDGES:
            recite.append({**cand, "_recite_reason": f"unknown_edge:{edge}"})
            continue

        # Check if this tree already has a terminal node
        overlay_trees = {
            str(t.get("tree_id") or ""): t
            for t in (overlays[bk].get("trees") or [])
        }
        existing_tree = overlay_trees.get(tree_id)
        if existing_tree:
            existing_nodes = existing_tree.get("nodes") or []
            if any(str(n.get("edge") or "") in _ALL_TERMINAL_EDGES
                   for n in existing_nodes):
                recite.append({**cand, "_recite_reason": "already_terminal"})
                continue

        to_insert.append((bk, tree_id, node, "confirmed"))

    return to_insert, recite


# ── per-ticker history onboard ────────────────────────────────────────────────

def run_history_onboard(
    ticker: str,
    *,
    seed_client: AnthropicClient,
    score_client: AnthropicClient,
    overlays: dict[str, dict],
    hand_typed_by_book: dict[str, list[dict]],
    budget_usd: float = 5.0,
    dry_run: bool = False,
    resume: bool = False,
    run_id: str = "",
) -> dict:
    """Run full history onboard for one ticker. Returns stats dict."""
    ticker_up = ticker.strip().upper()
    run_id = run_id or str(uuid.uuid4())
    bk = _book_key_for(ticker_up)

    stats: dict[str, Any] = {
        "ticker": ticker_up,
        "run_id": run_id,
        "seeds_proposed": 0,
        "seeds_inserted_confirmed": 0,
        "seeds_inserted_provisional": 0,
        "seeds_recite_queue": 0,
        "verdicts_proposed": 0,
        "verdicts_inserted": 0,
        "verdicts_recite_queue": 0,
        "regime_stub": "skipped",
        "errors": [],
    }

    # Resume check
    checkpoint = _load_checkpoint(ticker_up)
    seeding_done = resume and checkpoint.get("seeding_done", False)
    scoring_done = resume and checkpoint.get("scoring_done", False)

    print(f"  {'='*58}")
    print(f"  History Onboard: {ticker_up}  [run_id={run_id[:8]}]")
    if dry_run:
        print("  [DRY RUN]")
    if resume and (seeding_done or scoring_done):
        print(f"  Resuming from checkpoint (seeding_done={seeding_done}, scoring_done={scoring_done})")
    print(f"  {'='*58}")

    # ── Step 1: Regime stub ───────────────────────────────────────────────────
    try:
        api_key = seed_client.api_key if hasattr(seed_client, "api_key") else os.getenv("ANTHROPIC_API_KEY")
        ensure_regime_stubs([ticker_up], api_key=api_key)
        stats["regime_stub"] = "ok"
        print(f"  {ticker_up}: regime stub ensured")
    except Exception as exc:
        stats["regime_stub"] = f"error: {exc}"
        stats["errors"].append(f"regime_stub: {exc}")

    # ── Step 2: Load cue rows ─────────────────────────────────────────────────
    missed = _load_all_cue_rows(ticker_up)
    print(f"  {ticker_up}: {len(missed)} cue rows found")

    # ── Step 3: Seed proposal (Haiku) ─────────────────────────────────────────
    proposals: list[dict] = []
    if not seeding_done:
        if missed:
            print(f"  {ticker_up}: proposing seeds via Haiku ({SEED_MODEL})...")
            try:
                proposals = propose_seeds(ticker_up, missed, seed_client)
                for p in proposals:
                    p.setdefault("book", "desk_hc_v2" if bk == "hc" else "desk_ops_v2")
                    if p.get("materiality") not in MATERIALITY_LEVELS:
                        p["materiality"] = infer_materiality(p)
            except Exception as exc:
                stats["errors"].append(f"propose_seeds: {exc}")
                print(f"  [WARN] {ticker_up}: seed proposal failed: {exc}")
        else:
            print(f"  {ticker_up}: no cue rows — skipping seed proposal")

        stats["seeds_proposed"] = len(proposals)
        print(f"  {ticker_up}: {len(proposals)} seeds proposed")

        # ── Step 4: Apply seed gate ───────────────────────────────────────────
        if proposals:
            to_insert, recite = _apply_seed_gate(
                proposals, overlays[bk], hand_typed_by_book.get(bk, []),
                dry_run=dry_run, run_id=run_id,
            )
            stats["seeds_recite_queue"] = len(recite)
            for _bk, cand, status in to_insert:
                if status == "confirmed":
                    stats["seeds_inserted_confirmed"] += 1
                else:
                    stats["seeds_inserted_provisional"] += 1
                if not dry_run:
                    append_tree(
                        overlays[_bk], cand,
                        provenance=_prov(
                            status, run_id=run_id,
                            confidence=str(cand.get("confidence") or ""),
                        ),
                    )
            if not dry_run and to_insert:
                save_overlay(bk, overlays[bk])
                print(
                    f"  {ticker_up}: overlay saved "
                    f"({stats['seeds_inserted_confirmed']} confirmed, "
                    f"{stats['seeds_inserted_provisional']} provisional)"
                )

        _save_checkpoint(ticker_up, {**stats, "seeding_done": True, "scoring_done": False})
    else:
        print(f"  {ticker_up}: seeding already done — skipping")

    # ── Step 5: Terminal scoring (Sonnet) ─────────────────────────────────────
    if not scoring_done:
        print(f"  {ticker_up}: scoring open trees via Sonnet ({SCORE_MODEL})...")
        try:
            cands, needs_review = score_ticker(
                ticker_up,
                budget_usd=budget_usd,
                client=score_client,
                plan_only=dry_run,
            )
        except Exception as exc:
            stats["errors"].append(f"score_ticker: {exc}")
            cands = []
            print(f"  [WARN] {ticker_up}: terminal scoring failed: {exc}")

        stats["verdicts_proposed"] = len(cands)
        print(f"  {ticker_up}: {len(cands)} verdicts proposed")

        # ── Step 6: Apply verdict gate ────────────────────────────────────────
        if cands:
            v_insert, v_recite = _apply_verdict_gate(
                cands, overlays, hand_typed_by_book,
                dry_run=dry_run,
            )
            stats["verdicts_recite_queue"] = len(v_recite)
            for _bk, tree_id, node, vstatus in v_insert:
                stats["verdicts_inserted"] += 1
                if not dry_run:
                    append_node(
                        overlays[_bk], tree_id, node,
                        provenance=_prov(vstatus, run_id=run_id),
                    )
            if not dry_run and v_insert:
                save_overlay("ops", overlays["ops"])
                save_overlay("hc", overlays["hc"])
                print(f"  {ticker_up}: {stats['verdicts_inserted']} verdicts applied")

        _save_checkpoint(ticker_up, {**stats, "seeding_done": True, "scoring_done": True,
                                      "completed_at": datetime.now(timezone.utc).isoformat()})
    else:
        print(f"  {ticker_up}: scoring already done — skipping")

    return stats


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        return 1

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ticker", action="append", metavar="TICKER",
                    help="Process one or more tickers (repeatable)")
    ap.add_argument("--all", dest="all_tickers", action="store_true",
                    help="Process all ops+HC tickers (except gold)")
    ap.add_argument("--budget-usd", type=float, default=5.0,
                    help="Sonnet scoring budget per ticker (default $5.00)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Gate decisions only — do NOT write overlays")
    ap.add_argument("--resume", action="store_true",
                    help="Skip already-completed stages per-ticker checkpoint")
    args = ap.parse_args(argv)

    if not args.ticker and not args.all_tickers:
        ap.error("specify --ticker TICKER or --all")

    # Build ticker list
    ops_tickers = [t for t in TECH_TICKERS if t not in GOLD_TICKERS]
    hc_tickers = [t for t in HC_TICKERS if t not in GOLD_TICKERS]
    all_known = list(dict.fromkeys(list(ops_tickers) + list(hc_tickers)))

    if args.ticker:
        tickers = [t.upper() for t in args.ticker if t.upper() not in GOLD_TICKERS]
    else:
        tickers = all_known

    run_id = str(uuid.uuid4())
    print(
        f"\nDesk History Onboard | run_id={run_id[:8]} | "
        f"{len(tickers)} ticker(s) | budget=${args.budget_usd:.2f}/ticker"
        + (" | DRY RUN" if args.dry_run else "")
        + (" | RESUME" if args.resume else "")
    )

    # Build clients
    seed_client = AnthropicClient(api_key=api_key, model=SEED_MODEL, max_retries=2)
    score_client = AnthropicClient(api_key=api_key, model=SCORE_MODEL, max_retries=1)

    # Load overlays and hand-typed catalogs
    overlays: dict[str, dict] = {
        "ops": load_overlay("ops"),
        "hc": load_overlay("hc"),
    }
    hand_typed_by_book: dict[str, list[dict]] = {
        "ops": list(OPS_TREES),
        "hc": list(HC_TREES),
    }

    # Process each ticker
    errors: list[str] = []
    all_stats: list[dict] = []

    for ticker in tickers:
        try:
            stats = run_history_onboard(
                ticker,
                seed_client=seed_client,
                score_client=score_client,
                overlays=overlays,
                hand_typed_by_book=hand_typed_by_book,
                budget_usd=args.budget_usd,
                dry_run=args.dry_run,
                resume=args.resume,
                run_id=run_id,
            )
            all_stats.append(stats)
            if stats["errors"]:
                errors.append(f"{ticker}: {stats['errors']}")
        except Exception as exc:
            errors.append(f"{ticker}: unhandled: {exc}")
            print(f"\n  [ERROR] {ticker}: {exc}", file=sys.stderr)

    # Rebuild books
    if not args.dry_run:
        try:
            write_ops_book()
            write_hc_book()
            print("\n  Books rebuilt.")
        except Exception as exc:
            print(f"\n  [WARN] Book rebuild failed: {exc}", file=sys.stderr)

    # Summary
    total_seeds = sum(s.get("seeds_inserted_confirmed", 0) + s.get("seeds_inserted_provisional", 0)
                      for s in all_stats)
    total_verdicts = sum(s.get("verdicts_inserted", 0) for s in all_stats)
    print(f"\n{'='*60}")
    print(f"  HISTORY ONBOARD COMPLETE")
    print(f"  Tickers: {len(tickers)}  |  Seeds inserted: {total_seeds}  |  Verdicts: {total_verdicts}")
    if errors:
        print(f"  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
