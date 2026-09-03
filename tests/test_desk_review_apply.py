"""Tests for scripts/_desk_review_apply.py.

All tests use tmp_path fixtures; no production data files are touched.
"""
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def overlay_dir(tmp_path: Path) -> Path:
    d = tmp_path / "desk_catalog_overlay"
    d.mkdir()
    return d


def _write_overlay(overlay_dir: Path, book: str, data: dict) -> None:
    (overlay_dir / f"{book}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def _read_overlay(overlay_dir: Path, book: str) -> dict:
    p = overlay_dir / f"{book}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _provisional_tree(tree_id: str, ticker: str = "IBM") -> dict:
    return {
        "tree_id": tree_id,
        "ticker": ticker,
        "kind": "promise",
        "bucket": "guidance",
        "title": f"Test {tree_id}",
        "seed": {"fiscal_period": "FY2023-Q1", "excerpt": "We will do X."},
        "nodes": [],
        "provenance": {"source": "autopilot", "status": "provisional"},
    }


@pytest.fixture()
def seed_candidates_data() -> dict:
    return {
        "candidates_by_ticker": {
            "IBM": [
                {
                    "tree_id": "ibm-test-promise",
                    "title": "Test promise",
                    "kind": "promise",
                    "bucket": "guidance",
                    "objects": ["EPS"],
                    "confidence": "high",
                    "book": "desk_ops_v2",
                    "seed": {
                        "fiscal_period": "FY2023-Q1",
                        "excerpt": "We will deliver X.",
                    },
                }
            ]
        }
    }


@pytest.fixture()
def terminal_candidates_data() -> dict:
    return {
        "candidates": [
            {
                "tree_id": "ibm-existing-tree",
                "ticker": "IBM",
                "kind": "promise",
                "bucket": "guidance",
                "proposed_edge": "delivered",
                "proposed_fiscal": "FY2024-Q1",
                "supporting_excerpt": "We delivered X as promised.",
                "confidence": "high",
                "reasoning": "Clear evidence of delivery.",
                "excerpt_verified": True,
            }
        ],
        "needs_review": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helper: import apply_decisions with patched DATA paths
# ─────────────────────────────────────────────────────────────────────────────

class _ApplyHarness:
    """Patches DATA-file paths inside _desk_review_apply so tests use tmp_path."""

    def __init__(
        self,
        tmp_path: Path,
        seed_data: dict,
        terminal_data: dict,
        ops_overlay_data: dict | None = None,
        hc_overlay_data: dict | None = None,
    ):
        self.tmp_path = tmp_path
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir(exist_ok=True)
        self.overlay_dir = self.data_dir / "desk_catalog_overlay"
        self.overlay_dir.mkdir(exist_ok=True)

        # Write seed / terminal candidate files
        (self.data_dir / "seed_batch_candidates.json").write_text(
            json.dumps(seed_data, indent=2), encoding="utf-8"
        )
        (self.data_dir / "terminal_score_candidates.json").write_text(
            json.dumps(terminal_data, indent=2), encoding="utf-8"
        )

        # Write overlays
        for book, data in (("ops", ops_overlay_data or {}), ("hc", hc_overlay_data or {})):
            (self.overlay_dir / f"{book}.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )

    def run(
        self,
        decisions: list[dict],
        dry_run: bool = False,
    ) -> dict:
        """Run apply_decisions with the tmp_path data files."""
        import scripts._desk_review_apply as mod

        # Patch DATA and OVERLAY paths to tmp_path equivalents
        orig_seed = mod.SEED_CANDIDATES_IN
        orig_terminal = mod.TERMINAL_CANDIDATES_IN
        orig_negatives = mod.NEGATIVES_OUT

        mod.SEED_CANDIDATES_IN = self.data_dir / "seed_batch_candidates.json"
        mod.TERMINAL_CANDIDATES_IN = self.data_dir / "terminal_score_candidates.json"
        mod.NEGATIVES_OUT = self.data_dir / "desk_seed_negatives.json"

        # Patch overlay I/O to use our tmp dir
        from scripts import _desk_catalog_overlay as ov_mod
        orig_dir = ov_mod.OVERLAY_DIR
        ov_mod.OVERLAY_DIR = self.overlay_dir
        ov_mod.OPS_OVERLAY = self.overlay_dir / "ops.json"
        ov_mod.HC_OVERLAY = self.overlay_dir / "hc.json"

        # Patch catalog imports to empty catalogs
        with (
            patch.object(mod, "_load_book_trees", return_value=([], [])),
            patch.object(mod, "write_ops_book", return_value={}),
            patch.object(mod, "write_hc_book", return_value={}),
            patch.object(mod, "write_sidecar", return_value=Path("/dev/null")),
            patch.object(mod, "write_workshop_html", return_value=Path("/dev/null")),
        ):
            result = mod.apply_decisions(decisions, dry_run=dry_run)

        # Restore
        mod.SEED_CANDIDATES_IN = orig_seed
        mod.TERMINAL_CANDIDATES_IN = orig_terminal
        mod.NEGATIVES_OUT = orig_negatives
        ov_mod.OVERLAY_DIR = orig_dir
        ov_mod.OPS_OVERLAY = orig_dir / "ops.json"
        ov_mod.HC_OVERLAY = orig_dir / "hc.json"

        return result

    def read_overlay(self, book: str) -> dict:
        p = self.overlay_dir / f"{book}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}

    def read_negatives(self) -> dict:
        p = self.data_dir / "desk_seed_negatives.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Accept seed — existing provisional tree → confirmed
# ─────────────────────────────────────────────────────────────────────────────

def test_accept_seed_confirms_provisional(tmp_path: Path, seed_candidates_data: dict, terminal_candidates_data: dict) -> None:
    """Accept on a seed whose tree is already provisional → status becomes confirmed."""
    existing_overlay = {
        "schema_version": "1",
        "trees": [_provisional_tree("ibm-test-promise", "IBM")],
        "nodes": {},
        "tombstones": [],
    }
    harness = _ApplyHarness(tmp_path, seed_candidates_data, terminal_candidates_data,
                            ops_overlay_data=existing_overlay)

    decisions = [{"row_id": "S:ibm-test-promise", "type": "seed", "ticker": "IBM",
                  "tree_id": "ibm-test-promise", "decision": "Accept", "materiality": None, "notes": None}]
    stats = harness.run(decisions)

    overlay = harness.read_overlay("ops")
    trees = {t["tree_id"]: t for t in (overlay.get("trees") or [])}
    assert "ibm-test-promise" in trees
    prov = trees["ibm-test-promise"].get("provenance") or {}
    assert prov.get("status") == "confirmed"
    assert stats["counts_by_decision"]["Accept"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Accept verdict — creates node with delivery_basis = transcript
# ─────────────────────────────────────────────────────────────────────────────

def test_accept_verdict_creates_confirmed_node(tmp_path: Path, seed_candidates_data: dict, terminal_candidates_data: dict) -> None:
    """Accept on a verdict → overlay.nodes gets a node with delivery_basis=transcript."""
    harness = _ApplyHarness(tmp_path, seed_candidates_data, terminal_candidates_data)

    decisions = [{"row_id": "V:ibm-existing-tree", "type": "verdict", "ticker": "IBM",
                  "tree_id": "ibm-existing-tree", "decision": "Accept", "materiality": None, "notes": None}]
    stats = harness.run(decisions)

    overlay = harness.read_overlay("ops")
    nodes = overlay.get("nodes") or {}
    assert "ibm-existing-tree" in nodes
    node_list = nodes["ibm-existing-tree"]
    assert len(node_list) == 1
    node = node_list[0]
    assert node["delivery_basis"] == "transcript"
    assert node["edge"] == "delivered"
    prov = node.get("provenance") or {}
    assert prov.get("status") == "confirmed"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Reject seed — tombstones; notes appear in negatives
# ─────────────────────────────────────────────────────────────────────────────

def test_reject_seed_tombstones_and_writes_negatives(tmp_path: Path, seed_candidates_data: dict, terminal_candidates_data: dict) -> None:
    """Reject on seed → tombstones the tree; notes in negatives file."""
    harness = _ApplyHarness(tmp_path, seed_candidates_data, terminal_candidates_data)

    decisions = [{"row_id": "S:ibm-test-promise", "type": "seed", "ticker": "IBM",
                  "tree_id": "ibm-test-promise", "decision": "Reject", "materiality": None,
                  "notes": "not a real promise — rhetoric"}]
    stats = harness.run(decisions)

    overlay = harness.read_overlay("ops")
    tombstones = overlay.get("tombstones") or []
    ts_ids = [ts["tree_id"] for ts in tombstones]
    assert "ibm-test-promise" in ts_ids
    ts = next(ts for ts in tombstones if ts["tree_id"] == "ibm-test-promise")
    assert ts["reason"] == "rejected"

    negatives = harness.read_negatives()
    neg_by_ticker = negatives.get("negatives_by_ticker") or {}
    assert "IBM" in neg_by_ticker
    neg_entries = neg_by_ticker["IBM"]
    assert any(n["tree_id"] == "ibm-test-promise" for n in neg_entries)

    assert stats["n_negatives_written"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Re-cite seed — tree appears in tombstones as retracted
# ─────────────────────────────────────────────────────────────────────────────

def test_recite_seed_retracts_tree(tmp_path: Path, seed_candidates_data: dict, terminal_candidates_data: dict) -> None:
    """Re-cite on seed → tree tombstoned with reason='retracted'."""
    harness = _ApplyHarness(tmp_path, seed_candidates_data, terminal_candidates_data)

    decisions = [{"row_id": "S:ibm-test-promise", "type": "seed", "ticker": "IBM",
                  "tree_id": "ibm-test-promise", "decision": "Re-cite", "materiality": None, "notes": None}]
    harness.run(decisions)

    overlay = harness.read_overlay("ops")
    tombstones = overlay.get("tombstones") or []
    ts_ids = {ts["tree_id"]: ts["reason"] for ts in tombstones}
    assert "ibm-test-promise" in ts_ids
    assert ts_ids["ibm-test-promise"] == "retracted"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Defer — overlay unchanged
# ─────────────────────────────────────────────────────────────────────────────

def test_defer_leaves_overlay_unchanged(tmp_path: Path, seed_candidates_data: dict, terminal_candidates_data: dict) -> None:
    """Defer → no mutation to overlay."""
    initial_overlay = {
        "schema_version": "1",
        "trees": [],
        "nodes": {},
        "tombstones": [],
    }
    harness = _ApplyHarness(tmp_path, seed_candidates_data, terminal_candidates_data,
                            ops_overlay_data=initial_overlay)

    decisions = [{"row_id": "S:ibm-test-promise", "type": "seed", "ticker": "IBM",
                  "tree_id": "ibm-test-promise", "decision": "Defer", "materiality": None, "notes": None}]
    harness.run(decisions)

    overlay = harness.read_overlay("ops")
    assert overlay.get("trees") == []
    assert overlay.get("tombstones") == []
    assert overlay.get("nodes") == {}


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Materiality override updates seed.materiality on overlay tree
# ─────────────────────────────────────────────────────────────────────────────

def test_materiality_override_updates_overlay_tree(tmp_path: Path, seed_candidates_data: dict, terminal_candidates_data: dict) -> None:
    """When decision has materiality='high', the accepted overlay tree's seed.materiality is updated."""
    existing_overlay = {
        "schema_version": "1",
        "trees": [_provisional_tree("ibm-test-promise", "IBM")],
        "nodes": {},
        "tombstones": [],
    }
    harness = _ApplyHarness(tmp_path, seed_candidates_data, terminal_candidates_data,
                            ops_overlay_data=existing_overlay)

    decisions = [{"row_id": "S:ibm-test-promise", "type": "seed", "ticker": "IBM",
                  "tree_id": "ibm-test-promise", "decision": "Accept", "materiality": "high", "notes": None}]
    harness.run(decisions)

    overlay = harness.read_overlay("ops")
    trees = {t["tree_id"]: t for t in (overlay.get("trees") or [])}
    assert "ibm-test-promise" in trees
    seed = trees["ibm-test-promise"].get("seed") or {}
    assert seed.get("materiality") == "high"
    assert seed.get("materiality_source") == "analyst_override"


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: dry-run — overlay NOT saved to disk
# ─────────────────────────────────────────────────────────────────────────────

def test_dry_run_does_not_save_overlay(tmp_path: Path, seed_candidates_data: dict, terminal_candidates_data: dict) -> None:
    """dry_run=True: decisions are computed but overlay file is not written."""
    initial_overlay = {
        "schema_version": "1",
        "trees": [_provisional_tree("ibm-test-promise", "IBM")],
        "nodes": {},
        "tombstones": [],
    }
    harness = _ApplyHarness(tmp_path, seed_candidates_data, terminal_candidates_data,
                            ops_overlay_data=initial_overlay)

    decisions = [{"row_id": "S:ibm-test-promise", "type": "seed", "ticker": "IBM",
                  "tree_id": "ibm-test-promise", "decision": "Reject", "materiality": None, "notes": "rhetoric"}]
    stats = harness.run(decisions, dry_run=True)

    # File on disk should be unmodified (no tombstone)
    overlay = harness.read_overlay("ops")
    tombstones = overlay.get("tombstones") or []
    assert len(tombstones) == 0, "dry_run must not write tombstone to disk"
    assert stats["dry_run"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: acceptance rates stats dict has correct keys
# ─────────────────────────────────────────────────────────────────────────────

def test_stats_dict_has_correct_keys(tmp_path: Path, seed_candidates_data: dict, terminal_candidates_data: dict) -> None:
    """apply_decisions returns a stats dict with all required keys."""
    harness = _ApplyHarness(tmp_path, seed_candidates_data, terminal_candidates_data)

    decisions = [
        {"row_id": "V:ibm-existing-tree", "type": "verdict", "ticker": "IBM",
         "tree_id": "ibm-existing-tree", "decision": "Accept", "materiality": None, "notes": None},
        {"row_id": "S:ibm-test-promise", "type": "seed", "ticker": "IBM",
         "tree_id": "ibm-test-promise", "decision": "Reject", "materiality": None, "notes": None},
    ]
    stats = harness.run(decisions)

    required_keys = {
        "dry_run",
        "n_decisions",
        "counts_by_decision",
        "counts_by_type",
        "acceptance_rates_by_confidence",
        "acceptance_rates_by_bucket",
        "n_negatives_written",
    }
    assert required_keys <= set(stats.keys())
    assert stats["n_decisions"] == 2
    assert stats["counts_by_decision"].get("Accept") == 1
    assert stats["counts_by_decision"].get("Reject") == 1
    # acceptance rates by confidence should have at least the "high" bucket
    assert "high" in stats["acceptance_rates_by_confidence"]
    rate_entry = stats["acceptance_rates_by_confidence"]["high"]
    assert "n" in rate_entry and "n_accept" in rate_entry and "accept_rate" in rate_entry
