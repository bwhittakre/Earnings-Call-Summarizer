"""Fixture tests for desk Path ID v1. Does not load the live book or novelty_view."""
from __future__ import annotations

import json

import pytest

from scripts._desk_path_id_v1 import (
    LOCKED_GENERATED_AT,
    assert_locked_stamp,
    coverage_bucket,
    fiscal_period_for,
    join_name_path,
    pick_excerpt,
    quarter_for_fiscal,
)
from scripts._path_id_v1 import LOCKED_GENERATED_AT as PATH_ID_STAMP
from services.earnings_monitor.dashboard.rank_ic_lab import (
    desk_excerpt_view,
    load_desk_path_id_v1,
    path_id_panel_model,
)


def _june_fye_rows() -> list[dict[str, str]]:
    return [
        {
            "ticker": "MSFT",
            "fiscal_period": "FY2021-Q4",
            "period_end_calendar_quarter": "2021-Q2",
        },
        {
            "ticker": "MSFT",
            "fiscal_period": "FY2021-Q3",
            "period_end_calendar_quarter": "2021-Q1",
        },
    ]


def test_calendar_2021q2_june_fye_maps_to_fy2021q4() -> None:
    assert fiscal_period_for("MSFT", "2021-Q2", _june_fye_rows()) == "FY2021-Q4"


def test_fiscal_missing_when_calendar_absent() -> None:
    assert fiscal_period_for("MSFT", "2019-Q4", _june_fye_rows()) is None


def test_verbatim_preferred_over_composite() -> None:
    quarter = {
        "fiscal_period": "FY2021-Q4",
        "novelties": [
            {
                "dimension": "competitive_position",
                "novelty_magnitude": 1.2,
                "rationale": "context only",
                "evidence": [
                    {
                        "claim": "composite claim",
                        "excerpt": "composite quote",
                        "verified": True,
                        "status": "composite",
                    },
                    {
                        "claim": "verbatim claim",
                        "excerpt": "verbatim quote",
                        "verified": True,
                        "status": "verbatim",
                    },
                ],
            }
        ],
    }
    picked = pick_excerpt(quarter)
    assert picked["excerpt"] == "verbatim quote"
    assert picked["claim"] == "verbatim claim"
    assert picked["excerpt_status"] == "verbatim"
    assert picked["novelty_magnitude"] == 1.2


def test_composite_used_when_no_verbatim() -> None:
    quarter = {
        "novelties": [
            {
                "dimension": "competitive_position",
                "novelty_magnitude": 0.4,
                "evidence": [
                    {
                        "claim": "only composite",
                        "excerpt": "composite only",
                        "verified": True,
                        "status": "composite",
                    }
                ],
            }
        ]
    }
    picked = pick_excerpt(quarter)
    assert picked["excerpt_status"] == "composite"
    assert picked["excerpt"] == "composite only"


def test_missing_excerpt_is_explicit_not_invented() -> None:
    quarter = {
        "novelties": [
            {
                "dimension": "competitive_position",
                "novelty_magnitude": 0.9,
                "evidence": [
                    {
                        "claim": "unverified",
                        "excerpt": "should not appear",
                        "verified": False,
                        "status": "verbatim",
                    }
                ],
            }
        ]
    }
    picked = pick_excerpt(quarter)
    assert picked["excerpt_status"] == "missing"
    assert picked["excerpt"] is None
    assert picked["claim"] is None
    assert "should not appear" not in str(picked.values())


def test_missing_excerpt_when_quarter_absent() -> None:
    picked = pick_excerpt(None)
    assert picked["excerpt_status"] == "missing"
    assert picked["excerpt"] is None


def test_quarter_for_fiscal_list_or_dict() -> None:
    listed = {"quarters": [{"fiscal_period": "FY2021-Q4", "novelties": []}]}
    keyed = {"quarters": {"FY2021-Q4": {"novelties": []}}}
    assert quarter_for_fiscal(listed, "FY2021-Q4") == {"fiscal_period": "FY2021-Q4", "novelties": []}
    assert quarter_for_fiscal(keyed, "FY2021-Q4") == {"novelties": []}
    assert quarter_for_fiscal(listed, "FY1999-Q1") is None


def test_join_missing_fiscal_does_not_invent_quote() -> None:
    excerpt = {
        "claim": "hallucinated",
        "excerpt": "do not use",
        "excerpt_status": "verbatim",
        "novelty_magnitude": 1.0,
    }
    row = join_name_path(
        {"period": "2021-Q2", "ticker": "MSFT", "predicted": "0_14", "realized": "0_14", "hit": True},
        None,
        excerpt,
    )
    assert row["fiscal_period"] is None
    assert row["excerpt"] is None
    assert row["claim"] is None
    assert row["excerpt_status"] == "missing"
    assert row["source"] is None
    assert coverage_bucket(row["fiscal_period"], row["excerpt_status"]) == "missing_fiscal"


def test_stamp_guard_accepts_locked_and_rejects_other() -> None:
    assert_locked_stamp(LOCKED_GENERATED_AT)
    assert LOCKED_GENERATED_AT == PATH_ID_STAMP
    with pytest.raises(SystemExit, match="refuses stamp"):
        assert_locked_stamp("2026-08-18T00:00:00+00:00")
    with pytest.raises(SystemExit, match="refuses stamp"):
        assert_locked_stamp(None)


def test_path_id_panel_model_still_fail_l2_only() -> None:
    model = path_id_panel_model(
        {
            "case_study_pass": False,
            "line1": False,
            "line2": True,
            "line3": False,
            "generated_at": LOCKED_GENERATED_AT,
            "split": "asof-path-id-17aug-book-v1",
            "hit_rate": 0.457143,
            "path_hits": 64,
            "path_scored": 140,
            "name_paths": [{"period": "2021-Q2", "ticker": "MSFT", "hit": True}],
        }
    )
    assert model["case_study_pass"] is False
    assert model["passing_lines"] == ["L2"]
    assert "FAIL" in model["caption"]
    assert "Do not promote a single line" in model["caption"]
    assert "L2" in model["caption"]
    assert "PASS" not in model["caption"]


def test_desk_excerpt_view_one_row() -> None:
    rows = [
        {"ticker": "MSFT", "period": "2021-Q2", "excerpt": "a", "excerpt_status": "verbatim"},
        {"ticker": "ORCL", "period": "2021-Q2", "excerpt": "b", "excerpt_status": "composite"},
    ]
    picked = desk_excerpt_view(rows, "MSFT 2021-Q2")
    assert picked is not None
    assert picked["excerpt"] == "a"
    assert desk_excerpt_view(rows, "ADBE 2021-Q2") is None


def test_load_desk_path_id_v1_stamp_guard(tmp_path) -> None:
    root = tmp_path / "cross_company"
    (root / "json").mkdir(parents=True)
    path = root / "json" / "desk_path_id_v1.json"
    path.write_text(
        json.dumps({"generated_at": "2026-01-01T00:00:00+00:00", "rows": []}),
        encoding="utf-8",
    )
    assert load_desk_path_id_v1(str(root)) is None
    path.write_text(
        json.dumps({"generated_at": LOCKED_GENERATED_AT, "rows": [{"ticker": "MSFT"}]}),
        encoding="utf-8",
    )
    loaded = load_desk_path_id_v1(str(root))
    assert loaded is not None
    assert loaded["rows"][0]["ticker"] == "MSFT"
