"""Catalog overlay: JSON side-files the autopilot writes instead of modifying Python catalogs.

The overlay system lets E2 (autopilot) propose new trees and nodes into the book
without touching the hand-typed Python catalog source files.  Human review
promotes provisional entries to confirmed or tombstones them.

Data files managed:
  data/desk_catalog_overlay/ops.json  — for ops book (TECH_TICKERS)
  data/desk_catalog_overlay/hc.json   — for HC book (HC_TICKERS)
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OVERLAY_DIR = ROOT / "data" / "desk_catalog_overlay"
OPS_OVERLAY = OVERLAY_DIR / "ops.json"
HC_OVERLAY = OVERLAY_DIR / "hc.json"
SCHEMA_VERSION = "1"


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _empty_scaffold() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "trees": [],
        "nodes": {},
        "tombstones": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Path helpers
# ─────────────────────────────────────────────────────────────────────────────

def _overlay_path(book: str) -> Path:
    """Return path for "ops" or "hc"."""
    if book == "ops":
        return OPS_OVERLAY
    if book == "hc":
        return HC_OVERLAY
    raise ValueError(f"unknown book {book!r}; expected 'ops' or 'hc'")


# ─────────────────────────────────────────────────────────────────────────────
# I/O
# ─────────────────────────────────────────────────────────────────────────────

def load_overlay(book: str) -> dict[str, Any]:
    """Load overlay file; return empty scaffold if missing."""
    path = _overlay_path(book)
    if not path.is_file():
        return _empty_scaffold()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return _empty_scaffold()
        # Ensure required keys exist (forward-compat for older files)
        raw.setdefault("schema_version", SCHEMA_VERSION)
        raw.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
        raw.setdefault("trees", [])
        raw.setdefault("nodes", {})
        raw.setdefault("tombstones", [])
        return raw
    except Exception:
        return _empty_scaffold()


def save_overlay(book: str, overlay: dict[str, Any]) -> None:
    """Write overlay to disk (creates OVERLAY_DIR if needed)."""
    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    path = _overlay_path(book)
    overlay["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(overlay, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Tombstone queries
# ─────────────────────────────────────────────────────────────────────────────

def is_tombstoned(tree_id: str, overlay: dict[str, Any]) -> bool:
    """True if tree_id appears in overlay tombstones."""
    return any(
        str(ts.get("tree_id") or "") == tree_id
        for ts in (overlay.get("tombstones") or [])
    )


# ─────────────────────────────────────────────────────────────────────────────
# Read accessors (return copies so callers cannot mutate internal state)
# ─────────────────────────────────────────────────────────────────────────────

def get_overlay_trees(overlay: dict[str, Any]) -> list[dict]:
    """Return the trees list from the overlay (copies)."""
    return [deepcopy(t) for t in (overlay.get("trees") or [])]


def get_overlay_nodes(overlay: dict[str, Any]) -> dict[str, list[dict]]:
    """Return the nodes dict from the overlay (copies). Keys are tree_ids."""
    return {k: [deepcopy(n) for n in v] for k, v in (overlay.get("nodes") or {}).items()}


# ─────────────────────────────────────────────────────────────────────────────
# Mutation helpers (all return the mutated overlay in-place; caller saves)
# ─────────────────────────────────────────────────────────────────────────────

def append_tree(overlay: dict[str, Any], tree_item: dict, *, provenance: dict) -> dict[str, Any]:
    """Add or replace a tree in overlay.trees (keyed on tree_id).

    - Skips if tree_id is tombstoned.
    - Attaches provenance to the item.
    - Returns the mutated overlay (in-place).
    - Does NOT save to disk (caller must call save_overlay).
    """
    tree_id = str(tree_item.get("tree_id") or "")
    if is_tombstoned(tree_id, overlay):
        return overlay

    item = deepcopy(tree_item)
    item["provenance"] = deepcopy(provenance)

    trees = overlay.setdefault("trees", [])
    # Replace if same tree_id already exists (idempotent update)
    for i, existing in enumerate(trees):
        if str(existing.get("tree_id") or "") == tree_id:
            trees[i] = item
            return overlay
    trees.append(item)
    return overlay


def append_node(
    overlay: dict[str, Any], tree_id: str, node: dict, *, provenance: dict
) -> dict[str, Any]:
    """Append a verdict node under overlay.nodes[tree_id].

    - Skips if tree_id is tombstoned.
    - Attaches provenance to the node.
    - Returns the mutated overlay (in-place).
    """
    if is_tombstoned(tree_id, overlay):
        return overlay

    n = deepcopy(node)
    n["provenance"] = deepcopy(provenance)

    nodes_dict = overlay.setdefault("nodes", {})
    nodes_dict.setdefault(tree_id, []).append(n)
    return overlay


def tombstone(
    overlay: dict[str, Any],
    tree_id: str,
    *,
    reason: str = "rejected",
    notes: str = "",
) -> dict[str, Any]:
    """Add tree_id to tombstones and remove from overlay.trees (and nodes).

    - Idempotent: no-op on the tombstone list if already present, but always
      scrubs the tree and node entries (so a re-call is still safe).
    - Returns the mutated overlay.
    """
    tombstones = overlay.setdefault("tombstones", [])
    if not is_tombstoned(tree_id, overlay):
        tombstones.append(
            {
                "tree_id": tree_id,
                "reason": reason,
                "tombstoned_at": datetime.now(timezone.utc).isoformat(),
                "notes": notes,
            }
        )

    # Remove from trees list
    trees = overlay.get("trees") or []
    overlay["trees"] = [t for t in trees if str(t.get("tree_id") or "") != tree_id]

    # Remove from nodes dict
    nodes_dict = overlay.get("nodes") or {}
    nodes_dict.pop(tree_id, None)
    overlay["nodes"] = nodes_dict

    return overlay


def retract_tree(overlay: dict[str, Any], tree_id: str) -> dict[str, Any]:
    """Retract a provisional tree (move to tombstones with reason='retracted').

    Same as tombstone but uses reason='retracted'.
    """
    return tombstone(overlay, tree_id, reason="retracted")


def confirm_tree(overlay: dict[str, Any], tree_id: str) -> dict[str, Any]:
    """Promote a provisional tree to confirmed (in-place status update)."""
    for tree in overlay.get("trees") or []:
        if str(tree.get("tree_id") or "") == tree_id:
            prov = tree.setdefault("provenance", {})
            prov["status"] = "confirmed"
            break
    return overlay


# ─────────────────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────────────────

def overlay_stats(overlay: dict[str, Any]) -> dict[str, Any]:
    """Count trees/nodes/tombstones by status."""
    trees = overlay.get("trees") or []
    n_provisional = sum(
        1 for t in trees if (t.get("provenance") or {}).get("status") == "provisional"
    )
    n_confirmed = sum(
        1 for t in trees if (t.get("provenance") or {}).get("status") == "confirmed"
    )

    nodes_dict = overlay.get("nodes") or {}
    total_nodes = sum(len(v) for v in nodes_dict.values())

    tombstones = overlay.get("tombstones") or []
    n_rejected = sum(1 for ts in tombstones if ts.get("reason") == "rejected")
    n_retracted = sum(1 for ts in tombstones if ts.get("reason") == "retracted")

    return {
        "n_trees": len(trees),
        "n_provisional": n_provisional,
        "n_confirmed": n_confirmed,
        "n_node_trees": len(nodes_dict),
        "n_total_nodes": total_nodes,
        "n_tombstones": len(tombstones),
        "n_rejected": n_rejected,
        "n_retracted": n_retracted,
    }
