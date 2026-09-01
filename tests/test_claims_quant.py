"""Quant runner and known-delivered. Fixture-only. No Snowflake."""
from __future__ import annotations

from scripts._desk_trees_v2 import build_tree, known_delivered_counts
from services.earnings_monitor.dashboard.claims_quant import (
    QUANT_STAMP,
    apply_node,
    compare_actual,
    first_check_fiscal,
    load_desk_quant_v2,
    quant_verdict,
    stop_fiscal,
)


def _clocked(**overrides: object) -> dict:
    item = {
        "tree_id": "adsk-flex-launch",
        "ticker": "ADSK",
        "kind": "promise",
        "title": "Flex launch",
        "objects": ("Flex",),
        "quant": {"measure": 20, "op": "gte", "threshold": 1.0},
        "seed": {
            "fiscal_period": "FY2022-Q2",
            "clock": "FY2022-Q3",
            "excerpt": "At the end of September, we will launch Flex.",
            "status": "verbatim",
        },
        "nodes": (),
    }
    item.update(overrides)
    return build_tree(item)


def _unclocked(**overrides: object) -> dict:
    item = {
        "tree_id": "strw-150-160-spend",
        "ticker": "STRW",
        "kind": "goal",
        "title": "Spend bogey",
        "objects": ("$150 to $160 million",),
        "expire": "FY2027-Q3",
        "quant": {
            "measure": 22,
            "op": "between",
            "threshold": [150, 160],
            "unit": "million",
            "silence_quarters": 4,
            "unclocked_cap_quarters": 8,
        },
        "seed": {
            "fiscal_period": "FY2025-Q3",
            "clock": None,
            "excerpt": "Our bogey is $150 to $160 million spent a year.",
            "status": "verbatim",
        },
        "nodes": (),
    }
    item.update(overrides)
    return build_tree(item)


def test_compare_actual_between_and_missing() -> None:
    assert compare_actual(155, "between", [150, 160]) is True
    assert compare_actual(140, "between", [150, 160]) is False
    assert compare_actual(None, "between", [150, 160]) is None
    assert compare_actual(200, "gte", 150) is True


def test_clocked_check_is_on_or_after_clock() -> None:
    tree = _clocked()
    assert first_check_fiscal(tree) == "FY2022-Q3"
    before = quant_verdict(tree, as_of="FY2022-Q2", actuals=[])
    assert before["verdict"] == "pending"
    at_clock = quant_verdict(tree, as_of="FY2022-Q3", actuals=[])
    assert at_clock["verdict"] in {"inconclusive", "expired"}
    assert at_clock["first_check"] == "FY2022-Q3"


def test_deferred_clock_moves_quant_check() -> None:
    tree = _clocked(
        nodes=(
            {
                "fiscal_period": "FY2022-Q4",
                "edge": "deferred",
                "old_clock": "FY2022-Q3",
                "clock": "FY2023-Q2",
                "excerpt": "Flex now lands next year.",
            },
        )
    )
    assert tree["clock"] == "FY2023-Q2"
    assert first_check_fiscal(tree) == "FY2023-Q2"
    early = quant_verdict(tree, as_of="FY2022-Q4", actuals=[])
    assert early["verdict"] == "pending"


def test_unclocked_silence_then_cap() -> None:
    tree = _unclocked()
    assert first_check_fiscal(tree) == "FY2026-Q3"
    assert stop_fiscal(tree) == "FY2027-Q3"
    early = quant_verdict(tree, as_of="FY2026-Q2", actuals=[])
    assert early["verdict"] == "pending"
    deny = quant_verdict(
        tree,
        as_of="FY2027-Q3",
        actuals=[
            {
                "measure": 22,
                "fiscal_period": "FY2027-Q2",
                "actual_value": 90,
                "period_role": "fy1",
            }
        ],
    )
    assert deny["verdict"] == "denied"
    empty = quant_verdict(tree, as_of="FY2027-Q3", actuals=[])
    assert empty["verdict"] == "expired"


def test_apply_quant_close_is_typed_basis() -> None:
    tree = _unclocked()
    denied = apply_node(tree, {"verdict": "denied", "stop_fiscal": "FY2027-Q3"})
    assert denied is not None
    assert denied["edge"] == "missed"
    assert denied["delivery_basis"] == "quant"
    expired = apply_node(tree, {"verdict": "expired", "stop_fiscal": "FY2027-Q3"})
    assert expired is not None
    assert expired["edge"] == "expired"


def test_expired_stays_unknown_in_known_delivered() -> None:
    tree = build_tree(
        {
            "tree_id": "ibm-promontory-watson",
            "ticker": "IBM",
            "kind": "promise",
            "title": "Watson",
            "objects": ("Watson",),
            "expire": "FY2018-Q3",
            "seed": {
                "fiscal_period": "FY2016-Q3",
                "excerpt": "We will train Watson.",
                "status": "verbatim",
            },
            "nodes": ({"fiscal_period": "FY2018-Q3", "edge": "expired"},),
        }
    )
    row = quant_verdict(tree, as_of="FY2018-Q3")
    assert row["verdict"] == "expired"
    counts = known_delivered_counts([tree], "FY2018-Q3")
    assert counts["n_unknown"] == 1
    assert counts["n_confirmed"] == 0


def test_loader_refuses_foreign_stamps(tmp_path) -> None:
    folder = tmp_path / "cross_company" / "json"
    folder.mkdir(parents=True)
    path = folder / "desk_quant_v2.json"
    path.write_text(
        '{"generated_at": "2026-08-27T18:02:00+00:00", "books": {}}',
        encoding="utf-8",
    )
    assert load_desk_quant_v2(tmp_path) is None
    path.write_text(
        f'{{"generated_at": "{QUANT_STAMP}", "books": {{}}}}',
        encoding="utf-8",
    )
    loaded = load_desk_quant_v2(tmp_path)
    assert loaded is not None
