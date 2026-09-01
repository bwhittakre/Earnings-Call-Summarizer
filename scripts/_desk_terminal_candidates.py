"""LLM-assisted terminal scoring for open ops + HC trees.

For each open tree, gathers post-seed novelty evidence and calls Claude to
propose a terminal edge (delivered / hit / missed / expired / none).

Outputs data/terminal_score_candidates.json for human review.

Rules:
- Does NOT auto-insert into any catalog.
- Gold book (NVDA) excluded — "No new LLM on the gold run".
- Only processes trees with state == "open".
- Output file carries "Do not auto-insert" header.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from scripts._desk_trees_v2_recall import (  # noqa: E402
    collect_candidates,
    novelty_path,
    novelty_periods,
    fiscal_key,
)
from scripts._desk_regimes_builder import (  # noqa: E402
    load_desk_trees_ops_v2,
    load_desk_trees_hc_v2,
)
from scripts._desk_seed_batch import excerpt_verified  # noqa: E402
from src.llm.anthropic_client import AnthropicClient, extract_json  # noqa: E402

# ── constants ────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-5"

OUT = ROOT / "data" / "terminal_score_candidates.json"

MAX_EVIDENCE_PER_TREE = 20  # cap to keep prompts reasonable

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are an experienced equity analyst closing out a claims-desk tree.
    A claims-desk tree tracks whether management delivered on a specific
    forward-looking statement. Your job: given the original seed statement
    and subsequent earnings call excerpts, propose the most appropriate
    terminal outcome.

    Terminal edge options:
      "delivered"  — promise was clearly fulfilled (use for kind=promise)
      "hit"        — goal was achieved (use for kind=goal)
      "missed"     — explicitly failed to deliver / admitted miss
      "expired"    — promised timeframe passed with no evidence either way
      "none"       — insufficient evidence to close; tree should remain open

    Respond with a JSON object:
    {
      "proposed_edge": "delivered|hit|missed|expired|none",
      "proposed_fiscal": "FY20XX-QX or null",
      "supporting_excerpt": "the single most relevant excerpt, verbatim",
      "confidence": "high|medium|low",
      "reasoning": "2-3 sentences explaining your conclusion"
    }

    If you are not confident (confidence=low) or cannot find clear evidence,
    set proposed_edge to "none". Never guess at a terminal just to close the tree.
    """
).strip()


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_novelty(ticker: str) -> dict | None:
    path = novelty_path(ticker)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _post_seed_periods(novelty: dict, seed_fiscal: str) -> list[str]:
    """Return all novelty periods strictly after seed_fiscal."""
    all_periods = novelty_periods(novelty)
    return [p for p in all_periods if fiscal_key(p) > fiscal_key(seed_fiscal)]


def _object_mentions(excerpt: str, objects: Sequence[str]) -> bool:
    """True if any object name appears in the excerpt (case-insensitive)."""
    lo = excerpt.lower()
    for obj in objects:
        if obj.lower() in lo:
            return True
    return False


def _gather_evidence(
    novelty: dict,
    seed_fiscal: str,
    objects: Sequence[str],
    ticker: str,
) -> list[dict]:
    """Collect post-seed novelty excerpts that mention the tree's objects."""
    post_periods = _post_seed_periods(novelty, seed_fiscal)
    if not post_periods:
        return []
    all_candidates = collect_candidates(novelty, post_periods, ticker=ticker)
    # Filter to excerpts mentioning any of the tree's objects (if objects provided)
    if objects:
        relevant = [
            c for c in all_candidates
            if _object_mentions(str(c.get("excerpt") or ""), objects)
        ]
        # Fall back to all candidates if filtering produces nothing
        if not relevant:
            relevant = all_candidates
    else:
        relevant = all_candidates
    return relevant[:MAX_EVIDENCE_PER_TREE]


def _build_user_content(tree: dict, evidence: list[dict]) -> str:
    ticker = tree.get("ticker", "?")
    tree_id = tree.get("tree_id", "?")
    kind = tree.get("kind", "promise")
    seed = tree.get("seed") or {}
    seed_fp = seed.get("fiscal_period", "?")
    seed_excerpt = str(seed.get("excerpt") or "").strip()
    clock = tree.get("clock") or seed.get("clock")
    objects = tree.get("objects") or []

    lines = [
        f"Company: {ticker}",
        f"Tree: {tree_id}",
        f"Kind: {kind}",
        f"Seed fiscal period: {seed_fp}",
        f"Clock (expected resolution): {clock or 'none stated'}",
        f"Objects being tracked: {', '.join(str(o) for o in objects) or 'not specified'}",
        "",
        "SEED STATEMENT:",
        f"  {seed_excerpt[:400]}",
        "",
        f"POST-SEED EVIDENCE ({len(evidence)} excerpts):",
    ]
    if not evidence:
        lines.append("  [No matching post-seed excerpts found in novelty view]")
    else:
        for i, ev in enumerate(evidence, 1):
            fp = ev.get("fiscal_period", "?")
            dim = ev.get("dimension", "?")
            exc = str(ev.get("excerpt") or "").strip()[:300]
            lines.append(f"  [{i}] fiscal={fp} dimension={dim}")
            lines.append(f"      {exc}")
    return "\n".join(lines)


def _proposed_node_py(result: dict, tree: dict) -> str:
    """Generate a ready-to-paste Python node dict matching the catalog schema."""
    edge = result.get("proposed_edge", "none")
    fiscal = result.get("proposed_fiscal") or ""
    excerpt = str(result.get("supporting_excerpt") or "").replace('"', '\\"')
    ticker = tree.get("ticker", "")
    tree_id = tree.get("tree_id", "")
    confidence = result.get("confidence", "low")
    lines = [
        "        # Proposed terminal node — review before inserting",
        "        {",
        f'            "edge": "{edge}",',
        f'            "fiscal_period": "{fiscal}",',
        f'            "excerpt": ("{excerpt[:280]}"),',
        f'            "dimension": "terminal",',
        f'            "status": "verbatim",',
        f'            # confidence={confidence}, tree={ticker}/{tree_id}',
        "        },",
    ]
    return "\n".join(lines)


def _process_tree(
    tree: dict,
    novelty: dict,
    client: AnthropicClient,
) -> dict | None:
    """Call LLM once for this tree; return enriched candidate or None on failure."""
    ticker = str(tree.get("ticker") or "").upper()
    tree_id = tree.get("tree_id", "?")
    seed = tree.get("seed") or {}
    seed_fp = str(seed.get("fiscal_period") or "")
    objects = [str(o) for o in (tree.get("objects") or [])]

    evidence = _gather_evidence(novelty, seed_fp, objects, ticker)
    user_content = _build_user_content(tree, evidence)
    label = f"{ticker}_{tree_id}_terminal"

    try:
        raw = client.client.messages.create(
            model=client.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        client._accumulate_usage(client._usage_from_response(raw.usage))
        raw_text = "".join(
            block.text for block in raw.content if block.type == "text"
        )
        result = extract_json(raw_text)
        # Guard: LLM occasionally wraps the object in an array
        if isinstance(result, list):
            result = result[0] if result else {}
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict, got {type(result).__name__}")
    except Exception as exc:
        print(f"  [WARN] LLM call failed for {ticker}/{tree_id}: {exc}", file=sys.stderr)
        return None

    edge = result.get("proposed_edge")
    # A scored verdict must quote real novelty text; "expired"/"none" carry no cite.
    verified = (
        excerpt_verified(result.get("supporting_excerpt"), evidence)
        if edge in ("delivered", "hit", "missed")
        else None
    )

    return {
        "ticker": ticker,
        "tree_id": tree_id,
        "kind": tree.get("kind"),
        "title": tree.get("title"),
        "seed_fiscal": seed_fp,
        "clock": tree.get("clock") or seed.get("clock"),
        "objects": objects,
        "n_evidence_excerpts": len(evidence),
        "proposed_edge": result.get("proposed_edge"),
        "proposed_fiscal": result.get("proposed_fiscal"),
        "supporting_excerpt": result.get("supporting_excerpt"),
        "excerpt_verified": verified,
        "confidence": result.get("confidence"),
        "reasoning": result.get("reasoning"),
        "proposed_node_py": _proposed_node_py(result, tree),
    }


def _write_output(
    candidates: list[dict],
    n_skipped_closed: int,
    n_skipped_no_novelty: int,
    *,
    complete: bool,
) -> dict:
    """Serialise current progress. Called after every tree so a crash keeps work."""
    n_actionable = sum(
        1 for c in candidates
        if c.get("proposed_edge") not in (None, "none")
        and c.get("confidence") in ("high", "medium")
    )
    n_unverified = sum(1 for c in candidates if c.get("excerpt_verified") is False)
    output = {
        "note": "LLM-proposed terminal verdicts. Do not auto-insert. Human review required.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": complete,
        "n_open_trees_scored": len(candidates),
        "n_skipped_closed": n_skipped_closed,
        "n_skipped_no_novelty": n_skipped_no_novelty,
        "n_actionable": n_actionable,
        "n_excerpt_unverified": n_unverified,
        "candidates": candidates,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set. Add it to .env.", file=sys.stderr)
        return 1

    client = AnthropicClient(api_key=api_key, model=MODEL, max_retries=1)

    ops_book = load_desk_trees_ops_v2()
    hc_book = load_desk_trees_hc_v2()

    candidates: list[dict] = []
    n_skipped_closed = 0
    n_skipped_no_novelty = 0

    for book_name, book in [("desk_ops_v2", ops_book), ("desk_hc_v2", hc_book)]:
        trees = book.get("trees") or []
        open_trees = [t for t in trees if t.get("open") or t.get("state") == "open"]
        print(f"\n{book_name}: {len(open_trees)}/{len(trees)} open trees")

        for tree in open_trees:
            ticker = str(tree.get("ticker") or "").upper()
            tree_id = tree.get("tree_id", "?")

            novelty = _load_novelty(ticker)
            if novelty is None:
                n_skipped_no_novelty += 1
                print(f"  {ticker}/{tree_id}: no novelty view — skipping")
                continue

            print(f"  {ticker}/{tree_id}: scoring...", end=" ", flush=True)
            result = _process_tree(tree, novelty, client)
            if result is None:
                print("FAILED")
                continue
            result["book"] = book_name
            candidates.append(result)
            edge = result.get("proposed_edge", "?")
            conf = result.get("confidence", "?")
            flag = " · excerpt UNVERIFIED" if result.get("excerpt_verified") is False else ""
            print(f"→ {edge} [{conf}]{flag}")
            _write_output(candidates, n_skipped_closed, n_skipped_no_novelty, complete=False)

        n_skipped_closed += len(trees) - len(open_trees)

    output = _write_output(candidates, n_skipped_closed, n_skipped_no_novelty, complete=True)

    print(f"\nWrote {OUT}")
    print(f"  Open trees scored : {len(candidates)}")
    print(f"  Actionable (not none, ≥ medium confidence): {output['n_actionable']}")
    print(f"  Excerpt unverified: {output['n_excerpt_unverified']} (scored verdict quotes text not in novelty view)")
    print(f"  Skipped (closed)  : {n_skipped_closed}")
    print(f"  Skipped (no novelty): {n_skipped_no_novelty}")
    print(f"\n{client.usage_summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
