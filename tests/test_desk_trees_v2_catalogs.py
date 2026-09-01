"""Ops first-seed catalog. Does not load NVIDIA gold."""
from __future__ import annotations

from scripts._desk_trees_v2 import BUCKETS, NVDA_STAMP, build_ops_book
from scripts._desk_trees_v2_catalogs import OPS_TREES
from scripts._desk_trees_v2_ops import OPS_STAMP, SEED_FIRST


def test_ops_catalog_has_v1_seven_and_skips_gold_stamp() -> None:
    tickers = {str(tree["ticker"]) for tree in OPS_TREES}
    assert set(SEED_FIRST) <= tickers
    assert "NVDA" not in tickers
    assert {"AVGO", "LRCX", "STRW"} <= tickers
    assert "APH" not in tickers
    payload = build_ops_book(OPS_TREES, {}, generated_at=OPS_STAMP, verify_excerpts=False)
    assert payload["generated_at"] == OPS_STAMP
    assert payload["generated_at"] != NVDA_STAMP
    assert payload["n_trees"] == len(OPS_TREES)
    by_id = {tree["tree_id"]: tree for tree in payload["trees"]}
    assert by_id["crm-20b-next-goal"]["goal_outcome"] == "hit"
    adi = by_id["adi-wireless-bms-deploy"]
    assert {tree["bucket"] for tree in payload["trees"]} <= set(BUCKETS)
    assert all(tree.get("bucket") for tree in payload["trees"])
    assert by_id["crm-20b-next-goal"]["bucket"] == "earnings_power"
    assert by_id["aapl-net-cash-neutral"]["bucket"] == "capital_allocation"
    assert by_id["avgo-45-op-margin"]["bucket"] == "margins"
    assert adi["bucket"] == "competitive_position"
    assert adi["goal_outcome"] == "became-promise"
    assert adi["current_kind"] == "promise"
    assert adi["kind_label"] == "promise (was goal)"
    assert adi["delivery"] == "unresolved"
    assert adi["open"] is True
    assert all(
        tree.get("delivery") != "delivered" for tree in payload["trees"]
    )
    assert all(
        tree.get("goal_outcome") != "hit" or tree["tree_id"] == "crm-20b-next-goal"
        for tree in payload["trees"]
    )
    ibm = by_id["ibm-promontory-watson"]
    assert ibm["delivery"] == "expired"
    assert ibm["open"] is False
    assert ibm["expire"] == "FY2018-Q3"
    assert ibm.get("quant") is None
    strw = by_id["strw-150-160-spend"]
    assert strw["expire"] == "FY2027-Q3"
    assert strw["open"] is True
    assert (strw.get("quant") or {}).get("measure") is None
    assert (strw.get("quant") or {}).get("op") == "between"
