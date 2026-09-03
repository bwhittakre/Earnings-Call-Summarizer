"""Tests for the catalog overlay module and its integration with the book builders.

Covers:
  1. load_overlay on missing file returns empty scaffold
  2. append_tree: adds tree, skips tombstoned, idempotent on same tree_id
  3. tombstone: moves tree to tombstones, removes from trees/nodes
  4. is_tombstoned: True for tombstoned ids
  5. overlay_stats: counts correctly
  6. write_ops_book with overlay: merges trees, carries n_provisional
  7. infer_materiality: correct level for all four rule paths
  8. deliver_rate_counts with materiality: weighted and material variants
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_catalog_overlay import (
    append_node,
    append_tree,
    confirm_tree,
    get_overlay_nodes,
    get_overlay_trees,
    is_tombstoned,
    load_overlay,
    overlay_stats,
    retract_tree,
    save_overlay,
    tombstone,
)
from scripts._desk_trees_v2 import (
    deliver_rate_counts,
    hit_rate_counts,
    infer_materiality,
)
from scripts._desk_trees_v2_ops import OPS_STAMP, write_ops_book


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _prov(status: str = "provisional") -> dict:
    return {
        "source": "autopilot",
        "status": status,
        "confidence": "high",
        "proposed_at": "2026-09-03T10:00:00+00:00",
        "model": "claude-sonnet-4-5",
        "run_id": "run-test-001",
    }


def _tree(tree_id: str, ticker: str = "MSFT") -> dict:
    return {
        "tree_id": tree_id,
        "ticker": ticker,
        "kind": "promise",
        "beat_id": "test",
        "bucket": "guidance",
        "title": f"Test tree {tree_id}",
        "objects": [],
        "seed": {
            "fiscal_period": "FY2026-Q1",
            "excerpt": "We will deliver on our targets.",
        },
        "nodes": [],
    }


def _built_tree(tree_id: str, delivery: str, materiality: str) -> dict:
    """Minimal built-tree dict (as produced by build_tree) for rate-count tests."""
    return {
        "tree_id": tree_id,
        "kind": "promise",
        "delivery": delivery,
        "goal_outcome": None,
        "seed": {"materiality": materiality},
    }


def _built_goal(tree_id: str, goal_outcome: str, materiality: str) -> dict:
    return {
        "tree_id": tree_id,
        "kind": "goal",
        "delivery": None,
        "goal_outcome": goal_outcome,
        "seed": {"materiality": materiality},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. load_overlay on missing file returns empty scaffold
# ─────────────────────────────────────────────────────────────────────────────

def test_load_overlay_missing_returns_scaffold(tmp_path, monkeypatch):
    """load_overlay("ops") on a missing file returns an empty scaffold."""
    import scripts._desk_catalog_overlay as mod

    monkeypatch.setattr(mod, "OVERLAY_DIR", tmp_path / "overlay")
    monkeypatch.setattr(mod, "OPS_OVERLAY", tmp_path / "overlay" / "ops.json")
    monkeypatch.setattr(mod, "HC_OVERLAY", tmp_path / "overlay" / "hc.json")

    result = mod.load_overlay("ops")
    assert result["schema_version"] == "1"
    assert result["trees"] == []
    assert result["nodes"] == {}
    assert result["tombstones"] == []
    assert "updated_at" in result


# ─────────────────────────────────────────────────────────────────────────────
# 2. append_tree: adds tree, skips tombstoned, idempotent on same tree_id
# ─────────────────────────────────────────────────────────────────────────────

def test_append_tree_adds_tree():
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    t = _tree("msft-guidance-2026")
    append_tree(overlay, t, provenance=_prov())
    assert len(overlay["trees"]) == 1
    assert overlay["trees"][0]["tree_id"] == "msft-guidance-2026"
    assert overlay["trees"][0]["provenance"]["status"] == "provisional"


def test_append_tree_skips_tombstoned():
    overlay: dict = {
        "schema_version": "1",
        "updated_at": "",
        "trees": [],
        "nodes": {},
        "tombstones": [{"tree_id": "msft-rejected", "reason": "rejected", "tombstoned_at": "x", "notes": ""}],
    }
    append_tree(overlay, _tree("msft-rejected"), provenance=_prov())
    assert overlay["trees"] == []


def test_append_tree_idempotent_on_same_tree_id():
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    t = _tree("msft-guidance-2026")
    append_tree(overlay, t, provenance=_prov("provisional"))
    # Second call with same tree_id (e.g. updated confidence) should replace, not append
    t2 = dict(t)
    append_tree(overlay, t2, provenance=_prov("confirmed"))
    assert len(overlay["trees"]) == 1
    assert overlay["trees"][0]["provenance"]["status"] == "confirmed"


# ─────────────────────────────────────────────────────────────────────────────
# 3. tombstone: moves tree to tombstones, removes from trees and nodes
# ─────────────────────────────────────────────────────────────────────────────

def test_tombstone_removes_from_trees_and_nodes():
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    append_tree(overlay, _tree("msft-guidance-2026"), provenance=_prov())
    append_node(overlay, "msft-guidance-2026", {"fiscal_period": "FY2026-Q2", "edge": "restated", "excerpt": "still on track."}, provenance=_prov())

    tombstone(overlay, "msft-guidance-2026", reason="rejected", notes="not relevant")

    assert len(overlay["trees"]) == 0
    assert "msft-guidance-2026" not in overlay["nodes"]
    assert len(overlay["tombstones"]) == 1
    assert overlay["tombstones"][0]["reason"] == "rejected"


def test_tombstone_is_idempotent():
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    append_tree(overlay, _tree("msft-guidance-2026"), provenance=_prov())
    tombstone(overlay, "msft-guidance-2026")
    tombstone(overlay, "msft-guidance-2026")  # second call
    assert len(overlay["tombstones"]) == 1


def test_retract_tree_uses_retracted_reason():
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    append_tree(overlay, _tree("msft-guidance-2026"), provenance=_prov())
    retract_tree(overlay, "msft-guidance-2026")
    assert overlay["tombstones"][0]["reason"] == "retracted"


# ─────────────────────────────────────────────────────────────────────────────
# 4. is_tombstoned: returns True for tombstoned ids
# ─────────────────────────────────────────────────────────────────────────────

def test_is_tombstoned_true_for_tombstoned():
    overlay: dict = {
        "schema_version": "1",
        "updated_at": "",
        "trees": [],
        "nodes": {},
        "tombstones": [{"tree_id": "rejected-tree", "reason": "rejected", "tombstoned_at": "x", "notes": ""}],
    }
    assert is_tombstoned("rejected-tree", overlay) is True
    assert is_tombstoned("not-rejected-tree", overlay) is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. overlay_stats: counts correctly
# ─────────────────────────────────────────────────────────────────────────────

def test_overlay_stats_counts_correctly():
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}

    append_tree(overlay, _tree("t1"), provenance=_prov("provisional"))
    append_tree(overlay, _tree("t2"), provenance=_prov("confirmed"))
    append_tree(overlay, _tree("t3"), provenance=_prov("provisional"))

    append_node(overlay, "t1", {"fiscal_period": "FY2026-Q2", "edge": "restated", "excerpt": "on track."}, provenance=_prov())
    append_node(overlay, "t1", {"fiscal_period": "FY2026-Q3", "edge": "restated", "excerpt": "still on track."}, provenance=_prov())

    tombstone(overlay, "t3", reason="rejected")
    overlay["tombstones"].append({"tree_id": "t-old", "reason": "retracted", "tombstoned_at": "x", "notes": ""})

    stats = overlay_stats(overlay)
    assert stats["n_trees"] == 2  # t1 and t2 (t3 tombstoned)
    assert stats["n_provisional"] == 1  # only t1
    assert stats["n_confirmed"] == 1  # t2
    assert stats["n_node_trees"] == 1  # only t1 has nodes
    assert stats["n_total_nodes"] == 2
    assert stats["n_tombstones"] == 2  # t3 (rejected) + t-old (retracted)
    assert stats["n_rejected"] == 1
    assert stats["n_retracted"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 6. write_ops_book with overlay: merges trees, carries n_provisional
# ─────────────────────────────────────────────────────────────────────────────

def _minimal_catalog_tree(tree_id: str, ticker: str) -> dict:
    """Minimal valid catalog entry that passes validate_catalog_tree."""
    return {
        "tree_id": tree_id,
        "ticker": ticker,
        "kind": "promise",
        "beat_id": "test",
        "bucket": "guidance",
        "title": f"Test: {tree_id}",
        "objects": [],
        "seed": {
            "fiscal_period": "FY2026-Q1",
            "excerpt": "We intend to deliver our targets.",
        },
        "nodes": [],
    }


def test_write_ops_book_with_overlay_merges_trees(tmp_path):
    """write_ops_book with overlay adds overlay tree to the book."""
    base_tree = _minimal_catalog_tree("base-tree-001", "MSFT")

    # Overlay with one provisional tree
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    overlay_tree = _minimal_catalog_tree("overlay-tree-001", "ORCL")
    append_tree(overlay, overlay_tree, provenance=_prov("provisional"))

    payload = write_ops_book(
        [base_tree],
        repo_root=tmp_path,
        verify_excerpts=False,
        overlay=overlay,
    )

    tree_ids = {t["tree_id"] for t in payload["trees"]}
    assert "base-tree-001" in tree_ids
    assert "overlay-tree-001" in tree_ids
    assert payload["n_trees"] == 2
    # n_provisional present in payload when overlay is supplied
    assert "n_provisional" in payload
    assert "n_confirmed_overlay" in payload
    # The provisional count: overlay_tree built with provenance.status = "provisional"
    assert payload["n_provisional"] == 1
    assert payload["n_confirmed_overlay"] == 0


def test_write_ops_book_tombstoned_tree_excluded(tmp_path):
    """A tombstoned overlay tree must not appear in the built book."""
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    overlay_tree = _minimal_catalog_tree("overlay-tree-rejected", "ORCL")
    append_tree(overlay, overlay_tree, provenance=_prov("provisional"))
    tombstone(overlay, "overlay-tree-rejected")

    payload = write_ops_book(
        [],
        repo_root=tmp_path,
        verify_excerpts=False,
        overlay=overlay,
    )
    tree_ids = {t["tree_id"] for t in payload["trees"]}
    assert "overlay-tree-rejected" not in tree_ids
    assert payload["n_trees"] == 0


def test_write_ops_book_no_overlay_unchanged(tmp_path):
    """write_ops_book without overlay behaves exactly as before (no new keys injected)."""
    base_tree = _minimal_catalog_tree("base-tree-002", "MSFT")
    payload = write_ops_book(
        [base_tree],
        repo_root=tmp_path,
        verify_excerpts=False,
    )
    assert payload["n_trees"] == 1
    # n_provisional should NOT be present when no overlay is passed
    assert "n_provisional" not in payload


# ─────────────────────────────────────────────────────────────────────────────
# 7. infer_materiality: correct level for all four rule paths
# ─────────────────────────────────────────────────────────────────────────────

def test_infer_materiality_earnings_power_bucket():
    item = {"bucket": "earnings_power", "title": "Deliver 20% operating margin", "objects": []}
    assert infer_materiality(item) == "high"


def test_infer_materiality_capital_allocation_bucket():
    item = {"bucket": "capital_allocation", "title": "Buy back shares", "objects": []}
    assert infer_materiality(item) == "high"


def test_infer_materiality_guidance_bucket():
    item = {"bucket": "guidance", "title": "Guide to 10% revenue growth", "objects": []}
    assert infer_materiality(item) == "high"


def test_infer_materiality_numeric_object():
    """A numeric term in objects triggers high even if bucket is neutral."""
    item = {
        "bucket": "demand",
        "title": "Grow AI business",
        "objects": ["$5 billion revenue target", "AI services"],
    }
    assert infer_materiality(item) == "high"


def test_infer_materiality_numeric_anchor():
    """A numeric term in match.anchors triggers high."""
    item = {
        "bucket": "competitive_position",
        "title": "Maintain leadership",
        "objects": [],
        "match": {"anchors": ["achieve 30% market share"], "context": []},
    }
    assert infer_materiality(item) == "high"


def test_infer_materiality_management_confidence_bucket():
    item = {"bucket": "management_confidence", "title": "Stay committed to our strategy", "objects": []}
    assert infer_materiality(item) == "low"


def test_infer_materiality_macro_regulatory_risk_bucket():
    item = {"bucket": "macro_regulatory_risk", "title": "Navigate tariff headwinds", "objects": []}
    assert infer_materiality(item) == "low"


def test_infer_materiality_low_keyword_in_title():
    item = {"bucket": "demand", "title": "Analyst Day 2026 targets", "objects": []}
    assert infer_materiality(item) == "low"


def test_infer_materiality_low_keyword_committed_to():
    item = {
        "bucket": "competitive_position",
        "title": "We remain committed to cloud leadership",
        "objects": [],
    }
    assert infer_materiality(item) == "low"


def test_infer_materiality_neutral_returns_medium():
    item = {
        "bucket": "demand",
        "title": "Grow enterprise software revenue",
        "objects": ["enterprise software"],
    }
    assert infer_materiality(item) == "medium"


def test_infer_materiality_no_bucket_neutral_title():
    item = {"title": "Continue expanding customer base", "objects": []}
    assert infer_materiality(item) == "medium"


# ─────────────────────────────────────────────────────────────────────────────
# 8. deliver_rate_counts with materiality
# ─────────────────────────────────────────────────────────────────────────────

def test_deliver_rate_counts_weighted_and_material():
    """Fixture: 2 high-mat delivered, 1 low-mat delivered, 1 medium-mat missed.

    Expected:
      delivered = 3, missed = 1, n_scoreable = 4
      deliver_rate = 3/4 = 0.75

      weights: high=3, low=1, medium=2
      w_delivered = 3+3+1 = 7, w_missed = 2, w_scoreable = 9
      weighted_deliver_rate = 7/9

      material (high only): 2 delivered, 0 missed → material_deliver_rate = 1.0
    """
    trees = [
        _built_tree("t1", "delivered", "high"),
        _built_tree("t2", "delivered", "high"),
        _built_tree("t3", "delivered", "low"),
        _built_tree("t4", "missed", "medium"),
    ]
    counts = deliver_rate_counts(trees)

    assert counts["delivered"] == 3
    assert counts["missed"] == 1
    assert counts["n_scoreable"] == 4
    assert counts["deliver_rate"] == pytest.approx(0.75)

    assert counts["weighted_delivered"] == 7
    assert counts["weighted_missed"] == 2
    assert counts["weighted_scoreable"] == 9
    assert counts["weighted_deliver_rate"] == pytest.approx(7 / 9)

    assert counts["material_delivered"] == 2
    assert counts["material_missed"] == 0
    assert counts["material_scoreable"] == 2
    assert counts["material_deliver_rate"] == pytest.approx(1.0)


def test_deliver_rate_counts_no_scoreable():
    """Empty scoreable set returns None for rates (no division by zero)."""
    counts = deliver_rate_counts([])
    assert counts["deliver_rate"] is None
    assert counts["weighted_deliver_rate"] is None
    assert counts["material_deliver_rate"] is None


def test_deliver_rate_counts_preserves_existing_keys():
    """Existing keys (delivered, missed, n_scoreable, deliver_rate) must still be present."""
    trees = [_built_tree("t1", "delivered", "high")]
    counts = deliver_rate_counts(trees)
    for key in ("delivered", "missed", "n_scoreable", "deliver_rate"):
        assert key in counts


def test_hit_rate_counts_weighted_and_material():
    """Fixture: 1 high-mat hit, 1 medium-mat hit, 1 low-mat missed.

    Expected:
      hit = 2, missed = 1, n_scoreable = 3
      hit_rate = 2/3

      w_hit = 3+2 = 5, w_missed = 1, w_scoreable = 6
      weighted_hit_rate = 5/6

      material: 1 hit, 0 missed → material_hit_rate = 1.0
    """
    goals = [
        _built_goal("g1", "hit", "high"),
        _built_goal("g2", "hit", "medium"),
        _built_goal("g3", "missed", "low"),
    ]
    counts = hit_rate_counts(goals)

    assert counts["hit"] == 2
    assert counts["missed"] == 1
    assert counts["n_scoreable"] == 3
    assert counts["hit_rate"] == pytest.approx(2 / 3)

    assert counts["weighted_hit"] == 5
    assert counts["weighted_missed"] == 1
    assert counts["weighted_scoreable"] == 6
    assert counts["weighted_hit_rate"] == pytest.approx(5 / 6)

    assert counts["material_hit"] == 1
    assert counts["material_missed"] == 0
    assert counts["material_scoreable"] == 1
    assert counts["material_hit_rate"] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Bonus: get_overlay_trees / get_overlay_nodes return deep copies
# ─────────────────────────────────────────────────────────────────────────────

def test_get_overlay_trees_returns_copies():
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    append_tree(overlay, _tree("t1"), provenance=_prov())
    trees = get_overlay_trees(overlay)
    trees[0]["title"] = "mutated"
    # Original should be untouched
    assert overlay["trees"][0]["title"] != "mutated"


def test_get_overlay_nodes_returns_copies():
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    append_node(overlay, "t1", {"fiscal_period": "FY2026-Q2", "edge": "restated", "excerpt": "x."}, provenance=_prov())
    nodes = get_overlay_nodes(overlay)
    nodes["t1"][0]["excerpt"] = "mutated"
    assert overlay["nodes"]["t1"][0]["excerpt"] != "mutated"


# ─────────────────────────────────────────────────────────────────────────────
# confirm_tree
# ─────────────────────────────────────────────────────────────────────────────

def test_confirm_tree_updates_status():
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    append_tree(overlay, _tree("t1"), provenance=_prov("provisional"))
    confirm_tree(overlay, "t1")
    assert overlay["trees"][0]["provenance"]["status"] == "confirmed"


def test_confirm_tree_noop_on_missing():
    """confirm_tree on an unknown tree_id should not raise."""
    overlay: dict = {"schema_version": "1", "updated_at": "", "trees": [], "nodes": {}, "tombstones": []}
    confirm_tree(overlay, "nonexistent")  # should not raise


# ─────────────────────────────────────────────────────────────────────────────
# save_overlay / load_overlay round-trip
# ─────────────────────────────────────────────────────────────────────────────

def test_save_and_load_overlay_round_trip(tmp_path, monkeypatch):
    import scripts._desk_catalog_overlay as mod

    monkeypatch.setattr(mod, "OVERLAY_DIR", tmp_path / "overlay")
    monkeypatch.setattr(mod, "OPS_OVERLAY", tmp_path / "overlay" / "ops.json")
    monkeypatch.setattr(mod, "HC_OVERLAY", tmp_path / "overlay" / "hc.json")

    overlay = mod.load_overlay("ops")  # scaffold
    mod.append_tree(overlay, _tree("round-trip"), provenance=_prov())
    mod.save_overlay("ops", overlay)

    reloaded = mod.load_overlay("ops")
    assert len(reloaded["trees"]) == 1
    assert reloaded["trees"][0]["tree_id"] == "round-trip"
