"""Tests for the Desk Autopilot module (E2).

Covers (no LLM calls; no real disk I/O except tmp_path):
  1. _is_duplicate: edge cases across overlay and hand-typed trees
  2. _apply_seed_gate: confirmed / provisional / recite_queue / tombstoned paths
  3. _apply_verdict_gate: free-tier verbatim → provisional; blocked paths
  4. --from-existing-candidates --dry-run: reads files, does NOT write overlay
  5. derive_regime_stub: mock index files → correct entry with fiscal periods
  6. overlay_stats after a seed+verdict insertion run
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_autopilot import (
    _apply_seed_gate,
    _apply_verdict_gate,
    _is_duplicate,
)
from scripts._desk_catalog_overlay import (
    append_node,
    append_tree,
    load_overlay,
    overlay_stats,
    save_overlay,
    tombstone,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _empty_overlay() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "updated_at": "2026-09-03T00:00:00+00:00",
        "trees": [],
        "nodes": {},
        "tombstones": [],
    }


def _make_seed_candidate(
    ticker: str = "AAPL",
    tree_id: str = "aapl-test-seed",
    excerpt: str = "We plan to launch the new product line in the second half of fiscal 2025.",
    confidence: str = "high",
    excerpt_verified: bool = True,
    book: str = "desk_ops_v2",
) -> dict:
    return {
        "tree_id": tree_id,
        "ticker": ticker,
        "kind": "promise",
        "bucket": "guidance",
        "title": "Launch new product line",
        "objects": ["new product line"],
        "match": {
            "anchors": ["new product line"],
            "context": ["launch", "second half"],
            "exclude": [],
            "generic": None,
        },
        "seed": {
            "fiscal_period": "FY2024-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2025-Q2",
            "excerpt": excerpt,
            "dimension": "demand",
            "status": "verbatim",
        },
        "confidence": confidence,
        "rationale": "Specific product launch commitment with clear timeline.",
        "materiality": "high",
        "materiality_rationale": "Thesis-level product launch with revenue implications.",
        "excerpt_verified": excerpt_verified,
        "book": book,
    }


def _make_verdict_candidate(
    ticker: str = "AAPL",
    tree_id: str = "aapl-existing-promise",
    proposed_edge: str = "delivered",
    excerpt_verified: bool = True,
    tier: int = 0,
    book: str = "desk_ops_v2",
) -> dict:
    return {
        "ticker": ticker,
        "tree_id": tree_id,
        "kind": "promise",
        "title": "Existing promise",
        "proposed_edge": proposed_edge,
        "proposed_fiscal": "FY2025-Q1",
        "supporting_excerpt": "We have now delivered the new product line.",
        "excerpt_verified": excerpt_verified,
        "confidence": "high",
        "retrieval": {"tier": tier, "n_sentences": 3},
        "book": book,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. _is_duplicate
# ─────────────────────────────────────────────────────────────────────────────

class TestIsDuplicate:
    def test_not_dup_on_empty_overlay(self):
        overlay = _empty_overlay()
        result = _is_duplicate(
            "aapl-test-seed",
            "We plan to launch the new product line in the second half of fiscal 2025.",
            "AAPL",
            overlay,
            [],
        )
        assert result is False

    def test_dup_on_same_tree_id(self):
        overlay = _empty_overlay()
        overlay["trees"].append({"tree_id": "aapl-test-seed", "ticker": "AAPL", "seed": {}})
        result = _is_duplicate("aapl-test-seed", "some excerpt", "AAPL", overlay, [])
        assert result is True

    def test_dup_on_same_excerpt_in_overlay(self):
        excerpt = "We plan to launch the new product line in the second half of fiscal 2025."
        overlay = _empty_overlay()
        overlay["trees"].append({
            "tree_id": "aapl-other-seed",
            "ticker": "AAPL",
            "seed": {"excerpt": excerpt},
        })
        result = _is_duplicate("aapl-new-seed", excerpt, "AAPL", overlay, [])
        assert result is True

    def test_not_dup_on_different_excerpt(self):
        overlay = _empty_overlay()
        overlay["trees"].append({
            "tree_id": "aapl-other-seed",
            "ticker": "AAPL",
            "seed": {"excerpt": "We will repurchase $90 billion of shares this year."},
        })
        result = _is_duplicate(
            "aapl-new-seed",
            "We plan to launch the new product line in the second half of fiscal 2025.",
            "AAPL",
            overlay,
            [],
        )
        assert result is False

    def test_dup_on_same_excerpt_in_hand_typed(self):
        excerpt = "We plan to launch the new product line in the second half of fiscal 2025."
        hand_typed = [
            {
                "tree_id": "aapl-hand-typed",
                "ticker": "AAPL",
                "seed": {"excerpt": excerpt},
            }
        ]
        result = _is_duplicate("aapl-new-seed", excerpt, "AAPL", _empty_overlay(), hand_typed)
        assert result is True

    def test_not_dup_different_ticker_same_excerpt(self):
        """Same excerpt for different ticker should not trigger dup."""
        excerpt = "We plan to launch the new product line in the second half of fiscal 2025."
        overlay = _empty_overlay()
        overlay["trees"].append({
            "tree_id": "msft-other-seed",
            "ticker": "MSFT",
            "seed": {"excerpt": excerpt},
        })
        result = _is_duplicate("aapl-new-seed", excerpt, "AAPL", overlay, [])
        assert result is False

    def test_short_excerpt_not_deduped_by_content(self):
        """Excerpts shorter than 24 chars skip content dedup (only tree_id matters)."""
        short = "We will do it."
        overlay = _empty_overlay()
        overlay["trees"].append({
            "tree_id": "aapl-other-seed",
            "ticker": "AAPL",
            "seed": {"excerpt": short},
        })
        # Different tree_id, short excerpt → NOT a dup
        result = _is_duplicate("aapl-new-seed", short, "AAPL", overlay, [])
        assert result is False

    def test_dup_on_substring_containment(self):
        """The new excerpt being a clean substring of an existing one counts as a dup.

        Note: trailing punctuation can break substring matching (the period on 'new'
        would not appear inside 'existing' which has more text after '2025').
        We test with a clean tail-free substring to match excerpt_covered behaviour
        from _desk_trees_v2_recall.py (which also does not strip punctuation).
        """
        existing = (
            "We plan to launch the new product line in the second half of fiscal 2025 "
            "across all major markets globally."
        )
        # new is a clean prefix of existing (no period that would break containment)
        new = (
            "We plan to launch the new product line in the second half of fiscal 2025 "
            "across all major markets"
        )
        overlay = _empty_overlay()
        overlay["trees"].append({
            "tree_id": "aapl-other",
            "ticker": "AAPL",
            "seed": {"excerpt": existing},
        })
        result = _is_duplicate("aapl-new", new, "AAPL", overlay, [])
        assert result is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. _apply_seed_gate
# ─────────────────────────────────────────────────────────────────────────────

class TestApplySeedGate:
    def _overlays(self, ops=None, hc=None):
        return {
            "ops": ops or _empty_overlay(),
            "hc": hc or _empty_overlay(),
        }

    def test_verbatim_high_gives_confirmed(self):
        cand = _make_seed_candidate(confidence="high", excerpt_verified=True)
        to_insert, recite = _apply_seed_gate(
            {"AAPL": [cand]}, self._overlays(), {"ops": [], "hc": []},
            from_existing=False, dry_run=True,
        )
        assert len(to_insert) == 1
        assert to_insert[0][2] == "confirmed"
        assert len(recite) == 0

    def test_verbatim_medium_gives_provisional(self):
        cand = _make_seed_candidate(confidence="medium", excerpt_verified=True)
        to_insert, recite = _apply_seed_gate(
            {"AAPL": [cand]}, self._overlays(), {"ops": [], "hc": []},
            from_existing=False, dry_run=True,
        )
        assert len(to_insert) == 1
        assert to_insert[0][2] == "provisional"

    def test_non_verbatim_goes_to_recite(self):
        cand = _make_seed_candidate(confidence="high", excerpt_verified=False)
        to_insert, recite = _apply_seed_gate(
            {"AAPL": [cand]}, self._overlays(), {"ops": [], "hc": []},
            from_existing=False, dry_run=True,
        )
        assert len(to_insert) == 0
        assert len(recite) == 1
        assert recite[0][2] == "excerpt_not_verified"

    def test_tombstoned_goes_to_recite(self):
        overlay = _empty_overlay()
        tombstone(overlay, "aapl-test-seed", reason="rejected")
        cand = _make_seed_candidate(confidence="high", excerpt_verified=True)
        to_insert, recite = _apply_seed_gate(
            {"AAPL": [cand]},
            {"ops": overlay, "hc": _empty_overlay()},
            {"ops": [], "hc": []},
            from_existing=False, dry_run=True,
        )
        assert len(to_insert) == 0
        assert len(recite) == 1
        assert recite[0][2] == "tombstoned"

    def test_duplicate_goes_to_recite(self):
        excerpt = "We plan to launch the new product line in the second half of fiscal 2025."
        overlay = _empty_overlay()
        overlay["trees"].append({
            "tree_id": "aapl-existing",
            "ticker": "AAPL",
            "seed": {"excerpt": excerpt},
        })
        cand = _make_seed_candidate(
            tree_id="aapl-new-seed", excerpt=excerpt,
            confidence="high", excerpt_verified=True,
        )
        to_insert, recite = _apply_seed_gate(
            {"AAPL": [cand]},
            {"ops": overlay, "hc": _empty_overlay()},
            {"ops": [], "hc": []},
            from_existing=False, dry_run=True,
        )
        assert len(to_insert) == 0
        assert len(recite) == 1
        assert recite[0][2] == "duplicate"

    def test_from_existing_high_verbatim_gives_confirmed(self):
        cand = _make_seed_candidate(confidence="high", excerpt_verified=True)
        to_insert, recite = _apply_seed_gate(
            {"AAPL": [cand]}, self._overlays(), {"ops": [], "hc": []},
            from_existing=True, dry_run=True,
        )
        assert len(to_insert) == 1
        assert to_insert[0][2] == "confirmed"

    def test_from_existing_medium_verbatim_gives_provisional(self):
        cand = _make_seed_candidate(confidence="medium", excerpt_verified=True)
        to_insert, recite = _apply_seed_gate(
            {"AAPL": [cand]}, self._overlays(), {"ops": [], "hc": []},
            from_existing=True, dry_run=True,
        )
        assert len(to_insert) == 1
        assert to_insert[0][2] == "provisional"

    def test_from_existing_non_verbatim_goes_to_recite(self):
        cand = _make_seed_candidate(confidence="high", excerpt_verified=False)
        to_insert, recite = _apply_seed_gate(
            {"AAPL": [cand]}, self._overlays(), {"ops": [], "hc": []},
            from_existing=True, dry_run=True,
        )
        assert len(to_insert) == 0
        assert recite[0][2] == "excerpt_not_verified"

    def test_hc_book_candidate_uses_hc_overlay(self):
        cand = _make_seed_candidate(
            ticker="LLY", tree_id="lly-test-seed",
            confidence="high", excerpt_verified=True,
            book="desk_hc_v2",
        )
        to_insert, recite = _apply_seed_gate(
            {"LLY": [cand]}, self._overlays(), {"ops": [], "hc": []},
            from_existing=False, dry_run=True,
        )
        assert len(to_insert) == 1
        assert to_insert[0][0] == "hc"


# ─────────────────────────────────────────────────────────────────────────────
# 3. _apply_verdict_gate
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyVerdictGate:
    def _overlays(self):
        return {"ops": _empty_overlay(), "hc": _empty_overlay()}

    def test_verbatim_free_tier_gives_provisional(self):
        cand = _make_verdict_candidate(
            proposed_edge="delivered", excerpt_verified=True, tier=0,
        )
        to_insert, recite = _apply_verdict_gate([cand], self._overlays(), dry_run=True)
        assert len(to_insert) == 1
        assert to_insert[0][3] == "provisional"
        assert to_insert[0][1] == "aapl-existing-promise"  # tree_id
        assert to_insert[0][2]["edge"] == "delivered"
        assert len(recite) == 0

    def test_tier3_passes_gate(self):
        cand = _make_verdict_candidate(
            proposed_edge="hit", excerpt_verified=True, tier=3,
            book="desk_hc_v2", ticker="LLY", tree_id="lly-tree",
        )
        to_insert, recite = _apply_verdict_gate([cand], self._overlays(), dry_run=True)
        assert len(to_insert) == 1
        assert to_insert[0][0] == "hc"

    def test_non_verbatim_goes_to_recite(self):
        cand = _make_verdict_candidate(excerpt_verified=False, tier=0)
        to_insert, recite = _apply_verdict_gate([cand], self._overlays(), dry_run=True)
        assert len(to_insert) == 0
        assert recite[0][2] == "excerpt_not_verified"

    def test_tier4_goes_to_recite(self):
        cand = _make_verdict_candidate(excerpt_verified=True, tier=4)
        to_insert, recite = _apply_verdict_gate([cand], self._overlays(), dry_run=True)
        assert len(to_insert) == 0
        assert "tier_too_high" in recite[0][2]

    def test_non_terminal_edge_goes_to_recite(self):
        cand = _make_verdict_candidate(proposed_edge="none", excerpt_verified=True, tier=0)
        to_insert, recite = _apply_verdict_gate([cand], self._overlays(), dry_run=True)
        assert len(to_insert) == 0
        assert "edge_not_terminal" in recite[0][2]

    def test_tombstoned_tree_goes_to_recite(self):
        overlay = _empty_overlay()
        tombstone(overlay, "aapl-existing-promise", reason="rejected")
        overlays = {"ops": overlay, "hc": _empty_overlay()}
        cand = _make_verdict_candidate(excerpt_verified=True, tier=0)
        to_insert, recite = _apply_verdict_gate([cand], overlays, dry_run=True)
        assert len(to_insert) == 0
        assert recite[0][2] == "tombstoned"

    def test_expired_edge_is_terminal(self):
        cand = _make_verdict_candidate(
            proposed_edge="expired", excerpt_verified=True, tier=1,
        )
        # Note: excerpt_verified may be None for expired (set to True for this test)
        cand["excerpt_verified"] = True
        to_insert, recite = _apply_verdict_gate([cand], self._overlays(), dry_run=True)
        assert len(to_insert) == 1

    def test_node_structure_correct(self):
        cand = _make_verdict_candidate(
            proposed_edge="delivered", excerpt_verified=True, tier=0,
        )
        cand["proposed_fiscal"] = "FY2025-Q1"
        cand["supporting_excerpt"] = "We have delivered the product."
        to_insert, _ = _apply_verdict_gate([cand], self._overlays(), dry_run=True)
        node = to_insert[0][2]
        assert node["edge"] == "delivered"
        assert node["fiscal_period"] == "FY2025-Q1"
        assert node["excerpt"] == "We have delivered the product."
        assert node["dimension"] == "terminal"
        assert node["status"] == "verbatim"


# ─────────────────────────────────────────────────────────────────────────────
# 4. --from-existing-candidates --dry-run: no overlay written
# ─────────────────────────────────────────────────────────────────────────────

class TestFromExistingDryRun:
    def test_dry_run_does_not_write_overlay(self, tmp_path, monkeypatch):
        """With --dry-run, save_overlay must never be called."""
        # Create minimal fake candidates files
        seed_file = tmp_path / "seed_batch_candidates.json"
        seed_file.write_text(
            json.dumps({
                "candidates_by_ticker": {
                    "AAPL": [_make_seed_candidate(confidence="high", excerpt_verified=True)]
                }
            }),
            encoding="utf-8",
        )

        term_file = tmp_path / "terminal_score_candidates.json"
        term_file.write_text(
            json.dumps({
                "candidates": [
                    _make_verdict_candidate(
                        proposed_edge="delivered", excerpt_verified=True, tier=0
                    )
                ]
            }),
            encoding="utf-8",
        )

        # Patch the path constants in the autopilot module
        import scripts._desk_autopilot as ap_mod

        monkeypatch.setattr(ap_mod, "OUT_SEEDS", seed_file)
        monkeypatch.setattr(ap_mod, "OUT_TERMS", term_file)

        # Track save_overlay calls
        saved_books: list[str] = []

        def fake_save_overlay(book: str, overlay: dict) -> None:
            saved_books.append(book)

        monkeypatch.setattr(ap_mod, "save_overlay", fake_save_overlay)
        # Also patch the imported save_overlay in _desk_catalog_overlay if used directly
        import scripts._desk_catalog_overlay as ov_mod

        monkeypatch.setattr(ov_mod, "save_overlay", fake_save_overlay)

        # Patch load_overlay to return empty scaffolds (no real files needed)
        monkeypatch.setattr(ap_mod, "load_overlay", lambda book: {
            "schema_version": "1",
            "updated_at": "2026-09-03T00:00:00+00:00",
            "trees": [], "nodes": {}, "tombstones": [],
        })

        # Patch rebuilders to no-ops
        monkeypatch.setattr(ap_mod, "_rebuild_books", lambda overlays, errors: None)
        monkeypatch.setattr(ap_mod, "_rebuild_sidecar", lambda errors: None)
        monkeypatch.setattr(ap_mod, "_rebuild_workshop", lambda errors: None)
        monkeypatch.setattr(ap_mod, "_write_ledger", lambda entry: None)

        rc = ap_mod.main(["--from-existing-candidates", "--ticker", "AAPL", "--dry-run"])
        assert rc == 0
        # With --dry-run, save_overlay must never have been called
        assert saved_books == [], f"save_overlay was called for: {saved_books}"

    def test_non_dry_run_writes_overlay(self, tmp_path, monkeypatch):
        """Without --dry-run, save_overlay IS called (at least once)."""
        seed_file = tmp_path / "seed_batch_candidates.json"
        seed_file.write_text(
            json.dumps({
                "candidates_by_ticker": {
                    "AAPL": [_make_seed_candidate(confidence="high", excerpt_verified=True)]
                }
            }),
            encoding="utf-8",
        )
        term_file = tmp_path / "terminal_score_candidates.json"
        term_file.write_text(json.dumps({"candidates": []}), encoding="utf-8")

        import scripts._desk_autopilot as ap_mod

        monkeypatch.setattr(ap_mod, "OUT_SEEDS", seed_file)
        monkeypatch.setattr(ap_mod, "OUT_TERMS", term_file)

        saved_books: list[str] = []

        def fake_save_overlay(book: str, overlay: dict) -> None:
            saved_books.append(book)

        monkeypatch.setattr(ap_mod, "save_overlay", fake_save_overlay)
        monkeypatch.setattr(ap_mod, "load_overlay", lambda book: {
            "schema_version": "1", "updated_at": "2026-09-03T00:00:00+00:00",
            "trees": [], "nodes": {}, "tombstones": [],
        })
        monkeypatch.setattr(ap_mod, "_rebuild_books", lambda overlays, errors: None)
        monkeypatch.setattr(ap_mod, "_rebuild_sidecar", lambda errors: None)
        monkeypatch.setattr(ap_mod, "_rebuild_workshop", lambda errors: None)
        monkeypatch.setattr(ap_mod, "_write_ledger", lambda entry: None)

        rc = ap_mod.main(["--from-existing-candidates", "--ticker", "AAPL"])
        assert rc == 0
        assert len(saved_books) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. derive_regime_stub: mock index files
# ─────────────────────────────────────────────────────────────────────────────

class TestDeriveRegimeStub:
    def _make_index_file(self, tmp_path: Path, ticker: str, fiscal: str, ceo_name: str) -> Path:
        base = tmp_path / "transcripts_index" / ticker.upper()
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{ticker.lower()}_{fiscal.replace('-', '_')}.json"
        path.write_text(
            json.dumps({
                "fiscal_period": fiscal,
                "paragraphs": [
                    {
                        "speaker": ceo_name,
                        "title": "Chief Executive Officer",
                        "role": "management",
                        "text": f"Good morning. I'm {ceo_name}, CEO of {ticker}.",
                    }
                ],
            }),
            encoding="utf-8",
        )
        return path

    def test_derives_stub_from_roster(self, tmp_path, monkeypatch):
        """derive_regime_stub extracts CEO from index paragraphs."""
        ticker = "ZZZZ"
        self._make_index_file(tmp_path, ticker, "FY2022-Q1", "Jane Doe")

        import scripts._desk_regimes_stub as stub_mod

        monkeypatch.setattr(stub_mod, "_INDEX_ROOT", tmp_path / "transcripts_index")
        monkeypatch.setattr(stub_mod, "_OVERLAY_PATH", tmp_path / "management_regimes_overlay.json")

        # Patch load_management_regimes to return no existing entries
        monkeypatch.setattr(stub_mod, "load_management_regimes", lambda: [])
        monkeypatch.setattr(stub_mod, "regimes_for_ticker", lambda ticker, regimes: [])

        entry = stub_mod.derive_regime_stub(ticker)
        assert entry is not None
        assert entry["ticker"] == ticker.upper()
        assert entry["named_person"] == "Jane Doe"
        assert entry["start_fiscal"] == "FY2022-Q1"
        assert entry["source"] == "transcript_roster"
        assert entry["provisional"] is True

    def test_earliest_fiscal_selected(self, tmp_path, monkeypatch):
        """When multiple index files exist, the earliest fiscal wins."""
        ticker = "ZZZB"
        self._make_index_file(tmp_path, ticker, "FY2023-Q1", "Bob Smith")
        self._make_index_file(tmp_path, ticker, "FY2021-Q3", "Bob Smith")  # earlier
        self._make_index_file(tmp_path, ticker, "FY2024-Q2", "Bob Smith")

        import scripts._desk_regimes_stub as stub_mod

        monkeypatch.setattr(stub_mod, "_INDEX_ROOT", tmp_path / "transcripts_index")
        monkeypatch.setattr(stub_mod, "_OVERLAY_PATH", tmp_path / "management_regimes_overlay.json")
        monkeypatch.setattr(stub_mod, "load_management_regimes", lambda: [])
        monkeypatch.setattr(stub_mod, "regimes_for_ticker", lambda ticker, regimes: [])

        entry = stub_mod.derive_regime_stub(ticker)
        assert entry is not None
        assert entry["start_fiscal"] == "FY2021-Q3"

    def test_no_index_files_returns_none(self, tmp_path, monkeypatch):
        """When there are no index files, derive_regime_stub returns None."""
        ticker = "NOIDX"
        import scripts._desk_regimes_stub as stub_mod

        monkeypatch.setattr(stub_mod, "_INDEX_ROOT", tmp_path / "transcripts_index")
        monkeypatch.setattr(stub_mod, "_OVERLAY_PATH", tmp_path / "management_regimes_overlay.json")
        monkeypatch.setattr(stub_mod, "load_management_regimes", lambda: [])
        monkeypatch.setattr(stub_mod, "regimes_for_ticker", lambda ticker, regimes: [])

        entry = stub_mod.derive_regime_stub(ticker)
        assert entry is None

    def test_already_catalogued_returns_none(self, tmp_path, monkeypatch):
        """If the ticker already has a regime entry, returns None (no force)."""
        ticker = "KNOWN"
        existing_entry = {"ticker": ticker, "role": "CEO", "named_person": "Alice"}

        import scripts._desk_regimes_stub as stub_mod

        monkeypatch.setattr(stub_mod, "_INDEX_ROOT", tmp_path / "transcripts_index")
        monkeypatch.setattr(stub_mod, "_OVERLAY_PATH", tmp_path / "management_regimes_overlay.json")
        monkeypatch.setattr(stub_mod, "load_management_regimes", lambda: [existing_entry])
        monkeypatch.setattr(stub_mod, "regimes_for_ticker", lambda t, r: [existing_entry])

        entry = stub_mod.derive_regime_stub(ticker)
        assert entry is None

    def test_force_rederives(self, tmp_path, monkeypatch):
        """force=True re-derives even when an entry already exists."""
        ticker = "FORCED"
        self._make_index_file(tmp_path, ticker, "FY2020-Q1", "New CEO")
        existing_entry = {"ticker": ticker, "role": "CEO", "named_person": "Old CEO"}

        import scripts._desk_regimes_stub as stub_mod

        monkeypatch.setattr(stub_mod, "_INDEX_ROOT", tmp_path / "transcripts_index")
        monkeypatch.setattr(stub_mod, "_OVERLAY_PATH", tmp_path / "management_regimes_overlay.json")
        monkeypatch.setattr(stub_mod, "load_management_regimes", lambda: [existing_entry])
        monkeypatch.setattr(stub_mod, "regimes_for_ticker", lambda t, r: [existing_entry])

        entry = stub_mod.derive_regime_stub(ticker, force=True)
        assert entry is not None
        assert entry["named_person"] == "New CEO"

    def test_overlay_file_written(self, tmp_path, monkeypatch):
        """derive_regime_stub writes the overlay file to disk."""
        ticker = "ZZZC"
        self._make_index_file(tmp_path, ticker, "FY2022-Q2", "Carol Jones")
        overlay_path = tmp_path / "management_regimes_overlay.json"

        import scripts._desk_regimes_stub as stub_mod

        monkeypatch.setattr(stub_mod, "_INDEX_ROOT", tmp_path / "transcripts_index")
        monkeypatch.setattr(stub_mod, "_OVERLAY_PATH", overlay_path)
        monkeypatch.setattr(stub_mod, "load_management_regimes", lambda: [])
        monkeypatch.setattr(stub_mod, "regimes_for_ticker", lambda t, r: [])

        stub_mod.derive_regime_stub(ticker)

        assert overlay_path.exists()
        content = json.loads(overlay_path.read_text(encoding="utf-8"))
        assert isinstance(content, list)
        assert any(e.get("ticker") == ticker.upper() for e in content)


# ─────────────────────────────────────────────────────────────────────────────
# 6. overlay_stats after seed + verdict insertion
# ─────────────────────────────────────────────────────────────────────────────

class TestOverlayStatsAfterRun:
    def test_stats_after_seed_and_verdict_insertion(self, tmp_path, monkeypatch):
        """overlay_stats reflects all insertions correctly."""
        import scripts._desk_catalog_overlay as ov_mod

        monkeypatch.setattr(ov_mod, "OVERLAY_DIR", tmp_path)
        monkeypatch.setattr(ov_mod, "OPS_OVERLAY", tmp_path / "ops.json")
        monkeypatch.setattr(ov_mod, "HC_OVERLAY", tmp_path / "hc.json")

        overlay = ov_mod.load_overlay("ops")  # empty scaffold

        prov_confirmed = {
            "source": "autopilot", "status": "confirmed",
            "run_id": "run-test", "proposed_at": "2026-09-03T00:00:00+00:00",
        }
        prov_provisional = {
            "source": "autopilot", "status": "provisional",
            "run_id": "run-test", "proposed_at": "2026-09-03T00:00:00+00:00",
        }
        prov_verdict = {
            "source": "autopilot", "status": "provisional",
            "run_id": "run-test", "proposed_at": "2026-09-03T00:00:00+00:00",
        }

        # Insert two seed trees
        seed1 = _make_seed_candidate(tree_id="aapl-seed-1", confidence="high")
        seed2 = _make_seed_candidate(tree_id="aapl-seed-2", confidence="medium",
                                      excerpt="We intend to grow our services revenue by 15% this fiscal year.")
        ov_mod.append_tree(overlay, seed1, provenance=prov_confirmed)
        ov_mod.append_tree(overlay, seed2, provenance=prov_provisional)

        # Insert one verdict node on an existing (hand-typed) tree
        node = {
            "edge": "delivered",
            "fiscal_period": "FY2025-Q1",
            "excerpt": "We have now delivered the new product line ahead of schedule.",
            "dimension": "terminal",
            "status": "verbatim",
        }
        ov_mod.append_node(overlay, "aapl-existing-hand-typed", node, provenance=prov_verdict)

        stats = ov_mod.overlay_stats(overlay)

        assert stats["n_trees"] == 2
        assert stats["n_confirmed"] == 1
        assert stats["n_provisional"] == 1
        assert stats["n_total_nodes"] == 1
        assert stats["n_tombstones"] == 0

    def test_stats_after_tombstone(self, tmp_path, monkeypatch):
        """Tombstoning a tree updates stats correctly."""
        import scripts._desk_catalog_overlay as ov_mod

        monkeypatch.setattr(ov_mod, "OVERLAY_DIR", tmp_path)
        monkeypatch.setattr(ov_mod, "OPS_OVERLAY", tmp_path / "ops.json")

        overlay = ov_mod.load_overlay("ops")
        prov = {"source": "autopilot", "status": "provisional", "run_id": "r"}

        seed = _make_seed_candidate(tree_id="aapl-seed-tombstone", confidence="high")
        ov_mod.append_tree(overlay, seed, provenance=prov)
        assert ov_mod.overlay_stats(overlay)["n_trees"] == 1

        ov_mod.tombstone(overlay, "aapl-seed-tombstone", reason="rejected")
        stats = ov_mod.overlay_stats(overlay)
        assert stats["n_trees"] == 0
        assert stats["n_tombstones"] == 1
        assert stats["n_rejected"] == 1
