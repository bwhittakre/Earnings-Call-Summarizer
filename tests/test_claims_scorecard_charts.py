"""Call scorecard visuals include every call, including unsettled ones."""
from services.earnings_monitor.dashboard.claims_scorecard import (
    _call_sequence_chart,
    _selected_fiscal_period,
    _snapshot_transparency_chart,
    timeline_rows,
)


def _row(**overrides):
    base = {
        "ticker": "CRWV",
        "fiscal_period": "FY2025-Q4",
        "period_kind": "fy",
        "event_name": None,
        "delivery_score": None,
        "transparency_score": 0.1,
        "n_new_seeds": 2,
        "open_trees_at_call": 4,
        "n_never_touched": 4,
        "n_silent": 4,
    }
    base.update(overrides)
    return base


def test_timeline_rows_keep_null_delivery_and_all_calls() -> None:
    rows = timeline_rows([
        _row(fiscal_period="FY2026-Q2", transparency_score=0.0273, n_new_seeds=1, open_trees_at_call=10),
        _row(
            fiscal_period="CONF-2025-08-27",
            period_kind="conf",
            event_name="Deutsche Bank 2025",
            transparency_score=0.3,
            n_new_seeds=4,
            open_trees_at_call=0,
        ),
        _row(fiscal_period="FY2025-Q1", transparency_score=0.0, n_new_seeds=0, open_trees_at_call=0),
    ])
    assert [r["fiscal_period"] for r in rows] == [
        "FY2025-Q1",
        "CONF-2025-08-27",
        "FY2026-Q2",
    ]
    assert all(r["delivery_label"] == "—" for r in rows)
    assert all(r["delivery_status"] == "Open book" for r in rows)
    db = next(r for r in rows if r["fiscal_period"] == "CONF-2025-08-27")
    assert db["call_type"] == "Conference"
    assert db["full_label"] == "Deutsche Bank 2025 (2025-08-27)"
    assert db["weight"] == 4


def test_sequence_chart_includes_every_row() -> None:
    rows = timeline_rows([
        _row(fiscal_period="FY2025-Q1", transparency_score=0.0, n_new_seeds=0, open_trees_at_call=0),
        _row(
            fiscal_period="CONF-2026-09-08",
            period_kind="conf",
            event_name="Goldman Sachs 2026",
            transparency_score=0.2,
            n_new_seeds=0,
            open_trees_at_call=14,
        ),
    ])
    chart = _call_sequence_chart(rows, "CRWV")
    payload = chart.to_dict()
    datasets = [layer.get("data", {}).get("values") for layer in payload.get("layer", [])]
    counts = [len(values or []) for values in datasets]
    assert counts and all(n == 2 for n in counts)


def test_snapshot_chart_includes_unsettled_tickers() -> None:
    rows = timeline_rows([
        _row(ticker="CRWV", fiscal_period="FY2026-Q2"),
        _row(ticker="AAPL", fiscal_period="FY2026-Q2", transparency_score=0.4),
    ])
    chart = _snapshot_transparency_chart(rows, "FY2026-Q2")
    values = chart.to_dict().get("data", {}).get("values") or []
    assert {row["ticker"] for row in values} == {"CRWV", "AAPL"}


def test_selected_fiscal_period_reads_streamlit_event() -> None:
    class _Sel:
        points = [{"fiscal_period": "CONF-2026-09-08"}]

    class _Event:
        selection = _Sel()

    assert _selected_fiscal_period(_Event()) == "CONF-2026-09-08"
    assert _selected_fiscal_period({"selection": {"call": [{"fiscal_period": "FY2026-Q2"}]}}) == "FY2026-Q2"
    assert _selected_fiscal_period(None) is None
