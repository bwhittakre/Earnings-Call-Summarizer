"""Pure helpers for the Claims Desk Roz page. No Streamlit."""
from __future__ import annotations

import json

from services.earnings_monitor.dashboard.claims_desk import (
    _LOCKED_STAMP,
    filter_rows_to_universe,
    format_deliver_rate,
    history_backdrop_window,
    kept_printed_facts,
    load_desk_claims_v1,
    promise_rows,
    same_beat_trail,
    shift_fiscal,
)


def test_shift_fiscal_pads_and_wraps() -> None:
    assert shift_fiscal("FY2022-Q2", -2) == "FY2021-Q4"
    assert shift_fiscal("FY2022-Q3", 2) == "FY2023-Q1"
    assert shift_fiscal("bad", 1) is None


def test_history_backdrop_window_highlights_seed_and_follow() -> None:
    history = [
        {"fiscal_period": "FY2021-Q4", "narrative_level": 1, "narrative_change": 0, "quant_z": 0, "narrative_quant_gap": 0},
        {"fiscal_period": "FY2022-Q1", "narrative_level": 2, "narrative_change": 0, "quant_z": 0, "narrative_quant_gap": 0},
        {"fiscal_period": "FY2022-Q2", "narrative_level": 3, "narrative_change": 0, "quant_z": 0, "narrative_quant_gap": 0},
        {"fiscal_period": "FY2022-Q3", "narrative_level": 4, "narrative_change": 0, "quant_z": 0, "narrative_quant_gap": 0},
        {"fiscal_period": "FY2022-Q4", "narrative_level": 5, "narrative_change": 0, "quant_z": 0, "narrative_quant_gap": 0},
        {"fiscal_period": "FY2023-Q1", "narrative_level": 6, "narrative_change": 0, "quant_z": 0, "narrative_quant_gap": 0},
        {"fiscal_period": "FY2024-Q1", "narrative_level": 9, "narrative_change": 0, "quant_z": 0, "narrative_quant_gap": 0},
    ]
    window = history_backdrop_window(history, "FY2022-Q2", "FY2022-Q3")
    periods = [row["fiscal_period"] for row in window]
    assert periods[0] == "FY2021-Q4"
    assert periods[-1] == "FY2023-Q1"
    assert "FY2024-Q1" not in periods
    seed = next(row for row in window if row["fiscal_period"] == "FY2022-Q2")
    follow = next(row for row in window if row["fiscal_period"] == "FY2022-Q3")
    assert seed["highlight"] is True and seed["role"] == "seed"
    assert follow["highlight"] is True and follow["role"] == "follow-up"


def test_history_backdrop_open_clock_runs_through_latest() -> None:
    history = [
        {"fiscal_period": "FY2026-Q4", "narrative_level": 1, "narrative_change": 0, "quant_z": 0, "narrative_quant_gap": 0},
        {"fiscal_period": "FY2027-Q1", "narrative_level": 2, "narrative_change": 0, "quant_z": 0, "narrative_quant_gap": 0},
        {"fiscal_period": "FY2027-Q2", "narrative_level": 3, "narrative_change": 0, "quant_z": 0, "narrative_quant_gap": 0},
    ]
    window = history_backdrop_window(history, "FY2027-Q1", None)
    periods = [row["fiscal_period"] for row in window]
    assert periods == ["FY2026-Q4", "FY2027-Q1", "FY2027-Q2"]
    assert window[-1]["role"] == ""


def test_same_beat_trail_skips_self() -> None:
    trail = same_beat_trail(
        [
            {"ticker": "ADSK", "period": "2021-Q2", "beat_id": "flex", "state": "kept", "delivery": "delivered"},
            {"ticker": "ADSK", "period": "2023-Q3", "beat_id": "flex", "state": "open", "delivery": "unresolved"},
            {"ticker": "CRM", "period": "2021-Q2", "beat_id": "slack-connect", "state": "kept", "delivery": "not-a-promise"},
        ],
        "flex",
        "ADSK 2021-Q2",
    )
    assert trail == [
        {"name": "ADSK 2023-Q3", "state": "open", "delivery": "unresolved"}
    ]


def test_promise_and_printed_fact_splits() -> None:
    rows = [
        {"claim_type": "forward_clock", "state": "kept"},
        {"claim_type": "printed_fact", "state": "kept"},
        {"claim_type": "pending_close", "state": "open"},
        {"claim_type": "completed_announcement", "state": "kept"},
    ]
    assert len(promise_rows(rows)) == 2
    assert len(kept_printed_facts(rows)) == 2


def test_format_deliver_rate_dash_when_unscored() -> None:
    assert format_deliver_rate(None) == "—"
    assert format_deliver_rate(1.0) == "100%"
    assert format_deliver_rate(0.5) == "50%"


def test_filter_rows_to_universe() -> None:
    rows = [{"ticker": "ADSK"}, {"ticker": "CRM"}]
    assert [row["ticker"] for row in filter_rows_to_universe(rows, ["adsk"])] == ["ADSK"]


def test_page_loader_refuses_wrong_stamp(tmp_path) -> None:
    root = tmp_path / "cross_company"
    (root / "json").mkdir(parents=True)
    path = root / "json" / "desk_claims_v1.json"
    path.write_text(
        json.dumps({"generated_at": "2026-01-01T00:00:00+00:00", "rows": []}),
        encoding="utf-8",
    )
    assert load_desk_claims_v1(str(root)) is None
    path.write_text(
        json.dumps({"generated_at": _LOCKED_STAMP, "rows": [{"ticker": "ADSK"}]}),
        encoding="utf-8",
    )
    loaded = load_desk_claims_v1(str(root))
    assert loaded is not None
    assert loaded["rows"][0]["ticker"] == "ADSK"
