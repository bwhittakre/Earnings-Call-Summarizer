"""Fixture tests for Path ID v1 helpers. Does not load the live book."""
from __future__ import annotations

import json

import pytest

from scripts._path_id_v1 import (
    LOCKED_GENERATED_AT,
    assert_locked_stamp,
    ex_post_path,
    path_signal_map,
    predict_path,
    top_tercile_tickers,
)
from services.earnings_monitor.dashboard.rank_ic_lab import (
    load_path_id_v1,
    path_id_panel_model,
)


def test_top_tercile_seven_names_takes_three() -> None:
    returns = {
        "A": 0.07,
        "B": 0.06,
        "C": 0.05,
        "D": 0.04,
        "E": 0.03,
        "F": 0.02,
        "G": 0.01,
    }
    assert top_tercile_tickers(returns) == {"A", "B", "C"}


def test_top_tercile_empty() -> None:
    assert top_tercile_tickers({}) == set()


def test_path_signal_flips_sign_for_top_tercile() -> None:
    novelty = {"HI": 2.0, "LO": 0.0, "MID": 1.0}
    signals = path_signal_map(novelty, {"HI"})
    assert signals is not None
    assert signals["HI"] < 0
    assert signals["LO"] < 0  # below-mean novelty, not top, stays negative z
    assert signals["MID"] == 0.0


def test_path_signal_undefined_when_novelty_flat() -> None:
    assert path_signal_map({"A": 1.0, "B": 1.0, "C": 1.0}, {"A"}) is None


def test_predict_path_rules() -> None:
    assert predict_path(in_top_tercile=True, novelty=0.0, novelty_median=1.0) == "0_14"
    assert predict_path(in_top_tercile=False, novelty=1.0, novelty_median=1.0) == "14_35"
    assert predict_path(in_top_tercile=False, novelty=0.5, novelty_median=1.0) == "35_56"


def test_ex_post_drops_ties() -> None:
    assert ex_post_path(0.3, 0.1, 0.05) == "0_14"
    assert ex_post_path(0.1, 0.4, 0.2) == "14_35"
    assert ex_post_path(0.1, 0.1, 0.5) == "35_56"
    assert ex_post_path(0.2, 0.2, 0.1) is None
    assert ex_post_path(0.3, 0.3, 0.3) is None


def test_stamp_guard_accepts_locked_and_rejects_other() -> None:
    assert_locked_stamp(LOCKED_GENERATED_AT)
    with pytest.raises(SystemExit, match="refuses stamp"):
        assert_locked_stamp("2026-08-18T00:00:00+00:00")
    with pytest.raises(SystemExit, match="refuses stamp"):
        assert_locked_stamp(None)


def test_path_id_panel_model_fail_with_l2() -> None:
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
    assert model["name_paths"][0]["ticker"] == "MSFT"


def test_load_path_id_v1_stamp_guard(tmp_path) -> None:
    root = tmp_path / "cross_company"
    (root / "json").mkdir(parents=True)
    path = root / "json" / "path_id_v1.json"
    path.write_text(
        json.dumps({"generated_at": "2026-01-01T00:00:00+00:00", "line2": True}),
        encoding="utf-8",
    )
    assert load_path_id_v1(str(root)) is None
    path.write_text(
        json.dumps({"generated_at": LOCKED_GENERATED_AT, "line2": True}),
        encoding="utf-8",
    )
    loaded = load_path_id_v1(str(root))
    assert loaded is not None
    assert loaded["line2"] is True
