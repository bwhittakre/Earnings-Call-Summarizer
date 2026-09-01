"""Fixture-only tests for scripts._desk_regimes.

All assertions run against in-memory fixtures: no Snowflake, no live builds.
"""
from __future__ import annotations

import pytest

from scripts._desk_regimes import (
    build_transfer_ledger,
    current_regime,
    load_management_regimes,
    regime_for_fiscal,
    regime_for_tree,
    regime_rate_counts,
    regimes_for_ticker,
    split_trees_by_regime,
    transfer_kind,
    transition_fiscals,
)

# ─────────────────────────────────────────────────────────────────────────────
# Minimal fixture catalog
# ─────────────────────────────────────────────────────────────────────────────

_REGIMES: list[dict] = [
    # Single-regime company (NVDA): Jensen Huang — no transition
    {
        "regime_id": "nvda-huang-ceo",
        "ticker": "NVDA",
        "role": "CEO",
        "named_person": "Jensen Huang",
        "start_fiscal": "FY2016-Q2",
        "end_fiscal": None,
        "succession_type": None,
        "notes": None,
    },
    # Two-regime company (IBM): Rometty → Krishna
    {
        "regime_id": "ibm-rometty-ceo",
        "ticker": "IBM",
        "role": "CEO",
        "named_person": "Ginni Rometty",
        "start_fiscal": "FY2016-Q3",
        "end_fiscal": "FY2019-Q4",
        "succession_type": "retirement",
        "notes": None,
    },
    {
        "regime_id": "ibm-krishna-ceo",
        "ticker": "IBM",
        "role": "CEO",
        "named_person": "Arvind Krishna",
        "start_fiscal": "FY2020-Q1",
        "end_fiscal": None,
        "succession_type": None,
        "notes": None,
    },
    # Three-regime company (CTSH): D'Souza → Humphries → Kumar
    {
        "regime_id": "ctsh-dsouza-ceo",
        "ticker": "CTSH",
        "role": "CEO",
        "named_person": "Francisco D'Souza",
        "start_fiscal": "FY2016-Q4",
        "end_fiscal": "FY2019-Q1",
        "succession_type": "retirement",
        "notes": None,
    },
    {
        "regime_id": "ctsh-humphries-ceo",
        "ticker": "CTSH",
        "role": "CEO",
        "named_person": "Brian Humphries",
        "start_fiscal": "FY2019-Q2",
        "end_fiscal": "FY2022-Q1",
        "succession_type": "resignation",
        "notes": None,
    },
    {
        "regime_id": "ctsh-kumar-ceo",
        "ticker": "CTSH",
        "role": "CEO",
        "named_person": "Ravi Kumar S",
        "start_fiscal": "FY2022-Q1",
        "end_fiscal": None,
        "succession_type": None,
        "notes": None,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Fixture trees
# ─────────────────────────────────────────────────────────────────────────────

def _make_tree(
    ticker: str,
    seed_fiscal: str,
    open_: bool = True,
    delivery: str = "unresolved",
    clock: str | None = None,
    nodes: list[dict] | None = None,
) -> dict:
    return {
        "tree_id": f"{ticker.lower()}-fixture",
        "ticker": ticker,
        "seed": {"fiscal_period": seed_fiscal},
        "open": open_,
        "delivery": delivery,
        "clock": clock,
        "nodes": nodes or [],
    }


# NVDA tree seeded inside Jensen Huang's reign — single regime expected
_NVDA_TREE = _make_tree("NVDA", "FY2017-Q1")

# IBM tree seeded under Rometty (FY2016-Q3), still open at Krishna transition
_IBM_OPEN_TREE = _make_tree("IBM", "FY2016-Q3", open_=True, clock="FY2019-Q3")

# IBM tree seeded under Rometty, closed (terminal) *before* the transition
_IBM_CLOSED_BEFORE_TREE = _make_tree(
    "IBM",
    "FY2016-Q3",
    open_=False,
    delivery="missed",
    nodes=[{"fiscal_period": "FY2018-Q2", "edge": "missed"}],
)

# IBM tree seeded under Rometty, new-regime (Krishna) provided the terminal
_IBM_CLOSED_BY_SUCCESSOR_TREE = _make_tree(
    "IBM",
    "FY2016-Q3",
    open_=False,
    delivery="delivered",
    nodes=[{"fiscal_period": "FY2020-Q3", "edge": "delivered"}],
)

# IBM tree seeded under Rometty, open at transition, has a post-transition non-silent node
_IBM_ADOPTED_TREE = _make_tree(
    "IBM",
    "FY2016-Q3",
    open_=True,
    nodes=[{"fiscal_period": "FY2020-Q2", "edge": "restated"}],
)

# IBM tree seeded under Rometty, open at transition, clock DUE at transition
_IBM_OVERDUE_TREE = _make_tree(
    "IBM",
    "FY2016-Q3",
    open_=True,
    clock="FY2019-Q4",  # clock expired before Krishna transition FY2020-Q1
)

# IBM tree seeded under Rometty, open, clock not yet due at transition
_IBM_IGNORED_TREE = _make_tree(
    "IBM",
    "FY2016-Q3",
    open_=True,
    clock="FY2025-Q1",  # far-future clock — not due at FY2020-Q1 transition
)

# CTSH tree seeded under D'Souza (FY2016-Q4) — tests multi-transition company
_CTSH_EARLY_OPEN_TREE = _make_tree(
    "CTSH",
    "FY2016-Q4",
    open_=True,
    clock="FY2025-Q1",  # not due at first transition
)


# ─────────────────────────────────────────────────────────────────────────────
# load_management_regimes
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadManagementRegimes:
    def test_loads_real_catalog(self):
        regimes = load_management_regimes()
        assert len(regimes) > 0, "Catalog should have at least one entry"
        first = regimes[0]
        assert "regime_id" in first
        assert "ticker" in first
        assert "start_fiscal" in first

    def test_missing_path_returns_empty(self, tmp_path):
        result = load_management_regimes(tmp_path / "nonexistent.json")
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# regime_for_fiscal
# ─────────────────────────────────────────────────────────────────────────────

class TestRegimeForFiscal:
    def test_returns_correct_regime_within_range(self):
        r = regime_for_fiscal("IBM", "FY2018-Q2", _REGIMES)
        assert r is not None
        assert r["regime_id"] == "ibm-rometty-ceo"

    def test_returns_correct_regime_at_start_boundary(self):
        r = regime_for_fiscal("IBM", "FY2016-Q3", _REGIMES)
        assert r is not None
        assert r["regime_id"] == "ibm-rometty-ceo"

    def test_returns_correct_regime_at_end_boundary(self):
        r = regime_for_fiscal("IBM", "FY2019-Q4", _REGIMES)
        assert r is not None
        assert r["regime_id"] == "ibm-rometty-ceo"

    def test_returns_new_regime_after_transition(self):
        r = regime_for_fiscal("IBM", "FY2020-Q1", _REGIMES)
        assert r is not None
        assert r["regime_id"] == "ibm-krishna-ceo"

    def test_returns_open_regime_for_future_fiscal(self):
        r = regime_for_fiscal("IBM", "FY2025-Q3", _REGIMES)
        assert r is not None
        assert r["regime_id"] == "ibm-krishna-ceo"

    def test_returns_none_for_fiscal_before_any_entry(self):
        # FY2015-Q1 is before ibm-rometty starts at FY2016-Q3
        r = regime_for_fiscal("IBM", "FY2015-Q1", _REGIMES)
        assert r is None

    def test_returns_none_for_unknown_ticker(self):
        r = regime_for_fiscal("UNKNOWN", "FY2020-Q1", _REGIMES)
        assert r is None

    def test_gap_between_regimes_returns_none(self):
        # FY2019-Q4+1 = FY2020-Q1 which IS covered; test a gap if one exists
        # For our IBM fixture, Rometty ends FY2019-Q4, Krishna starts FY2020-Q1 — no gap
        # For this test, manufacture a gap with a custom catalog
        gapped = [
            {
                "regime_id": "test-old",
                "ticker": "TEST",
                "role": "CEO",
                "named_person": "Old CEO",
                "start_fiscal": "FY2016-Q1",
                "end_fiscal": "FY2018-Q4",
                "succession_type": "retirement",
                "notes": None,
            },
            {
                "regime_id": "test-new",
                "ticker": "TEST",
                "role": "CEO",
                "named_person": "New CEO",
                "start_fiscal": "FY2019-Q2",  # Q1 2019 is a gap
                "end_fiscal": None,
                "succession_type": None,
                "notes": None,
            },
        ]
        r = regime_for_fiscal("TEST", "FY2019-Q1", gapped)
        assert r is None  # falls into the gap


# ─────────────────────────────────────────────────────────────────────────────
# transition_fiscals
# ─────────────────────────────────────────────────────────────────────────────

class TestTransitionFiscals:
    def test_single_regime_returns_empty(self):
        assert transition_fiscals("NVDA", _REGIMES) == []

    def test_two_regime_returns_one_transition(self):
        t = transition_fiscals("IBM", _REGIMES)
        assert t == ["FY2020-Q1"]

    def test_three_regime_returns_two_transitions(self):
        t = transition_fiscals("CTSH", _REGIMES)
        assert len(t) == 2
        assert t[0] == "FY2019-Q2"
        assert t[1] == "FY2022-Q1"


# ─────────────────────────────────────────────────────────────────────────────
# current_regime
# ─────────────────────────────────────────────────────────────────────────────

class TestCurrentRegime:
    def test_returns_open_entry(self):
        r = current_regime("IBM", _REGIMES)
        assert r is not None
        assert r["regime_id"] == "ibm-krishna-ceo"
        assert r["end_fiscal"] is None

    def test_single_regime_returns_itself(self):
        r = current_regime("NVDA", _REGIMES)
        assert r is not None
        assert r["regime_id"] == "nvda-huang-ceo"


# ─────────────────────────────────────────────────────────────────────────────
# transfer_kind
# ─────────────────────────────────────────────────────────────────────────────

class TestTransferKind:
    def test_single_regime_nvda(self):
        assert transfer_kind(_NVDA_TREE, _REGIMES) == "single_regime"

    def test_prior_closed(self):
        """Tree closed before the transition → prior_closed."""
        assert transfer_kind(_IBM_CLOSED_BEFORE_TREE, _REGIMES) == "prior_closed"

    def test_inherited_closed_by_successor(self):
        """Tree closed AFTER the transition by the new regime."""
        assert transfer_kind(_IBM_CLOSED_BY_SUCCESSOR_TREE, _REGIMES) == "inherited_closed_by_successor"

    def test_inherited_adopted(self):
        """New regime posted a non-silent node → adopted."""
        assert transfer_kind(_IBM_ADOPTED_TREE, _REGIMES) == "inherited_adopted"

    def test_inherited_overdue(self):
        """Open at transition, clock expired at transition date → overdue."""
        assert transfer_kind(_IBM_OVERDUE_TREE, _REGIMES) == "inherited_overdue"

    def test_inherited_ignored(self):
        """Open at transition, clock not yet due → ignored."""
        assert transfer_kind(_IBM_IGNORED_TREE, _REGIMES) == "inherited_ignored"

    def test_multi_transition_first_applies(self):
        """For a multi-regime company, the first applicable transition is used."""
        kind = transfer_kind(_CTSH_EARLY_OPEN_TREE, _REGIMES)
        # Seeded FY2016-Q4 under D'Souza; first transition is FY2019-Q2 (Humphries)
        # Clock FY2025-Q1 is not due at FY2019-Q2 → inherited_ignored
        assert kind == "inherited_ignored"


# ─────────────────────────────────────────────────────────────────────────────
# split_trees_by_regime
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitTreesByRegime:
    def test_buckets_trees_by_seed_regime(self):
        trees = [_NVDA_TREE, _IBM_CLOSED_BEFORE_TREE, _IBM_OPEN_TREE]
        buckets = split_trees_by_regime(trees, _REGIMES)
        assert "nvda-huang-ceo" in buckets
        assert len(buckets["nvda-huang-ceo"]) == 1
        assert "ibm-rometty-ceo" in buckets
        assert len(buckets["ibm-rometty-ceo"]) == 2

    def test_unknown_ticker_goes_to_unknown_bucket(self):
        unknown_tree = _make_tree("ZZZZZ", "FY2020-Q1")
        buckets = split_trees_by_regime([unknown_tree], _REGIMES)
        assert "unknown" in buckets


# ─────────────────────────────────────────────────────────────────────────────
# regime_rate_counts
# ─────────────────────────────────────────────────────────────────────────────

class TestRegimeRateCounts:
    def test_excludes_inherited_trees_from_current_regime(self):
        """Trees seeded under Rometty count for ibm-rometty, not ibm-krishna."""
        trees = [
            # Under Rometty: closed with missed
            _make_tree("IBM", "FY2016-Q3", open_=False, delivery="missed",
                       nodes=[{"fiscal_period": "FY2017-Q1", "edge": "missed"}]),
            # Under Krishna: delivered
            _make_tree("IBM", "FY2021-Q1", open_=False, delivery="delivered",
                       nodes=[{"fiscal_period": "FY2022-Q1", "edge": "delivered"}]),
        ]
        counts = regime_rate_counts(trees, _REGIMES, "FY2023-Q4")
        # Rometty bucket has 1 tree (missed → failed bucket in known_delivered)
        assert "ibm-rometty-ceo" in counts
        assert counts["ibm-rometty-ceo"]["n_failed"] == 1
        # Krishna bucket has 1 tree (delivered → confirmed bucket)
        assert "ibm-krishna-ceo" in counts
        assert counts["ibm-krishna-ceo"]["n_confirmed"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# build_transfer_ledger
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildTransferLedger:
    def test_single_regime_trees_excluded(self):
        ledger = build_transfer_ledger([_NVDA_TREE], _REGIMES)
        assert ledger == []

    def test_crossing_trees_included(self):
        trees = [_NVDA_TREE, _IBM_OPEN_TREE, _IBM_CLOSED_BEFORE_TREE]
        ledger = build_transfer_ledger(trees, _REGIMES)
        # IBM trees cross the boundary; NVDA does not
        assert len(ledger) == 2
        for entry in ledger:
            assert entry["ticker"] == "IBM"
            assert entry["transfer_kind"] in {
                "prior_closed",
                "inherited_adopted",
                "inherited_closed_by_successor",
                "inherited_overdue",
                "inherited_ignored",
            }

    def test_ledger_fields_present(self):
        ledger = build_transfer_ledger([_IBM_OVERDUE_TREE], _REGIMES)
        assert len(ledger) == 1
        entry = ledger[0]
        assert entry["transfer_kind"] == "inherited_overdue"
        assert entry["seed_fiscal"] == "FY2016-Q3"
        assert entry["transition_fiscal"] == "FY2020-Q1"
        assert entry["seed_regime"] == "ibm-rometty-ceo"


# ─────────────────────────────────────────────────────────────────────────────
# Integration: real catalog against real trees
# ─────────────────────────────────────────────────────────────────────────────

class TestRealCatalogIntegration:
    """Smoke tests using the live catalog and compiled tree catalogs."""

    def test_nvda_trees_all_single_regime(self):
        """All NVDA gold trees should be single_regime (Jensen Huang throughout)."""
        import scripts._desk_trees_v2_catalogs as ops_c
        from scripts._desk_trees_v2 import build_tree

        regimes = load_management_regimes()
        nvda_trees = [build_tree(t) for t in ops_c.OPS_TREES if t["ticker"] == "NVDA"]
        # NVDA is in the gold book, not the ops catalog — if absent, skip
        if not nvda_trees:
            pytest.skip("No NVDA trees in ops catalog")
        for tree in nvda_trees:
            assert transfer_kind(tree, regimes) == "single_regime"

    def test_ibm_tree_transfer_kind_is_not_single_regime(self):
        """IBM's Watson/Promontory tree crossed the Rometty→Krishna boundary."""
        import scripts._desk_trees_v2_catalogs as ops_c
        from scripts._desk_trees_v2 import build_tree

        regimes = load_management_regimes()
        ibm_trees = [build_tree(t) for t in ops_c.OPS_TREES if t["ticker"] == "IBM"]
        if not ibm_trees:
            pytest.skip("No IBM trees in ops catalog")
        for tree in ibm_trees:
            kind = transfer_kind(tree, regimes)
            assert kind != "single_regime", f"IBM tree should cross Rometty→Krishna: got {kind}"

    def test_regime_for_fiscal_across_all_tickers(self):
        """Smoke-check that regime_for_fiscal returns something for every tree seed."""
        import scripts._desk_trees_v2_catalogs as ops_c
        import scripts._desk_trees_v2_hc_catalogs as hc_c
        from scripts._desk_trees_v2 import build_tree

        regimes = load_management_regimes()
        all_defs = list(ops_c.OPS_TREES) + list(hc_c.HC_TREES)
        missing: list[str] = []
        for t_def in all_defs:
            tree = build_tree(t_def)
            fp = tree["seed"]["fiscal_period"]
            ticker = tree["ticker"]
            r = regime_for_fiscal(ticker, fp, regimes)
            if r is None:
                missing.append(f"{ticker}@{fp}")
        assert not missing, f"No regime found for: {missing}"
