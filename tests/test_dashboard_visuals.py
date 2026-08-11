"""Focused tests for Roz dashboard ranking helpers and Altair chart builders."""

from __future__ import annotations

from services.earnings_monitor.dashboard.charts import (
    heatmap_chart,
    narrative_quant_plotly,
    narrative_quant_scatter,
    narrative_quant_trajectory_plotly,
    overview_pulse_chart,
    ranked_bar_chart,
)
from services.earnings_monitor.dashboard.data import DashboardData
from services.earnings_monitor.dashboard.sectors import (
    ALL_COMPANIES,
    list_sector_options,
    pad_company_rows,
    resolve_sector_tickers,
)
from services.earnings_monitor.dashboard.views import VIEWS


def _sample_rows() -> list[dict]:
    return [
        {
            "ticker": "AAPL",
            "fiscal_period": "FY2025-Q1",
            "dimension": "margins",
            "llm_level": 1.2,
            "change_magnitude": 0.3,
            "quant_z": 0.4,
            "quant_z_pit": 0.4,
            "narrative_quant_gap": 0.8,
            "is_divergence": True,
            "any_quant_divergence": True,
            "history_incomplete": False,
            "quant_quality_ok": True,
            "quant_quality_flags": "[]",
        },
        {
            "ticker": "AAPL",
            "fiscal_period": "FY2025-Q1",
            "dimension": "demand",
            "llm_level": 0.5,
            "change_magnitude": 0.1,
            "quant_z": 0.6,
            "quant_z_pit": 0.6,
            "narrative_quant_gap": -0.1,
            "is_divergence": False,
            "any_quant_divergence": False,
            "history_incomplete": False,
            "quant_quality_ok": True,
            "quant_quality_flags": "[]",
        },
        {
            "ticker": "AAPL",
            "fiscal_period": "FY2025-Q2",
            "dimension": "margins",
            "llm_level": 1.0,
            "change_magnitude": 0.2,
            "quant_z": -0.2,
            "quant_z_pit": -0.2,
            "narrative_quant_gap": 1.2,
            "is_divergence": True,
            "any_quant_divergence": True,
            "history_incomplete": False,
            "quant_quality_ok": False,
            "quant_quality_flags": '["sparse_dimension"]',
        },
        {
            "ticker": "MSFT",
            "fiscal_period": "FY2025-Q2",
            "dimension": "margins",
            "llm_level": 0.2,
            "change_magnitude": 0.0,
            "quant_z": 0.1,
            "quant_z_pit": 0.1,
            "narrative_quant_gap": 0.1,
            "is_divergence": False,
            "any_quant_divergence": False,
            "history_incomplete": False,
            "quant_quality_ok": True,
            "quant_quality_flags": "[]",
        },
    ]


def test_views_rename_dimension_panel() -> None:
    assert "Dimension panel" in VIEWS
    assert "Dimension heatmap" not in VIEWS


def test_sector_options_include_all_and_xlk() -> None:
    options = list_sector_options()
    assert options[0] == ALL_COMPANIES
    assert "xlk_tech" in options


def test_resolve_sector_tickers_intersects() -> None:
    available = ["AAPL", "MSFT", "ZZZZ"]
    resolved = resolve_sector_tickers("xlk_tech", available)
    assert resolved == ["AAPL", "MSFT"]
    assert resolve_sector_tickers(ALL_COMPANIES, available) == available


def test_pad_company_rows_keeps_universe() -> None:
    rows = [{"ticker": "AAPL", "gap": 1.0}]
    padded = pad_company_rows(rows, ["AAPL", "MSFT", "NVDA"])
    assert [row["ticker"] for row in padded] == ["AAPL", "MSFT", "NVDA"]
    assert padded[1].get("gap") is None


def test_cross_company_includes_divergence_rate() -> None:
    data = DashboardData.from_records(_sample_rows())
    rows = data.cross_company(latest_periods=4)
    by_ticker = {row["ticker"]: row for row in rows}
    assert "divergence_rate" in by_ticker["AAPL"]
    assert by_ticker["AAPL"]["divergence_rate"] is not None
    assert by_ticker["AAPL"]["mean_quant_z"] is not None


def test_cross_company_dimension_scope() -> None:
    data = DashboardData.from_records(_sample_rows())
    rows = data.cross_company(latest_periods=4, dimension="margins")
    aapl = next(row for row in rows if row["ticker"] == "AAPL")
    assert aapl["scope"] == "margins"
    assert aapl["quarters"] == 2
    assert aapl["mean_narrative_quant_gap"] is not None


def test_overview_pulse_sorted_by_abs_gap() -> None:
    data = DashboardData.from_records(_sample_rows())
    pulse = data.overview_pulse()
    assert pulse
    assert pulse[0]["ticker"] == "AAPL"
    gaps = [row["abs_gap"] for row in pulse if row["abs_gap"] is not None]
    assert gaps == sorted(gaps, reverse=True)


def test_ranked_bar_keeps_null_companies() -> None:
    chart = ranked_bar_chart(
        [
            {
                "ticker": "AAPL",
                "mean_quant_z": 0.4,
                "latest_period": "FY2025-Q2",
                "quarters": 2,
            },
            {
                "ticker": "MSFT",
                "mean_quant_z": None,
                "latest_period": None,
                "quarters": 0,
            },
            {
                "ticker": "NVDA",
                "mean_quant_z": -0.1,
                "latest_period": "FY2025-Q2",
                "quarters": 1,
            },
        ],
        "mean_quant_z",
    )
    spec = chart.to_dict()
    assert "datasets" in spec or "data" in spec
    height = spec.get("height") or 0
    assert height >= 28 * 3
    y_scale = (spec.get("encoding") or {}).get("y", {}).get("scale") or {}
    assert len(y_scale.get("domain") or []) == 3


def test_overview_pulse_keeps_null_gap_and_breakdown() -> None:
    chart = overview_pulse_chart(
        [
            {
                "ticker": "AAPL",
                "fiscal_period": "FY2025-Q2",
                "gap": 1.2,
                "abs_gap": 1.2,
                "narrative_level": 1.0,
                "narrative_surprise": 0.8,
                "quant_z": -0.2,
                "quant_flagged": True,
                "incomplete": False,
            },
            {
                "ticker": "MSFT",
                "fiscal_period": None,
                "gap": None,
                "abs_gap": None,
                "narrative_level": None,
                "narrative_surprise": None,
                "quant_z": None,
                "quant_flagged": False,
                "incomplete": False,
            },
        ]
    )
    spec = chart.to_dict()
    encoded = str(spec)
    assert "gap_breakdown" in encoded
    assert "surprise" in encoded.lower()
    assert "not level" in encoded.lower() or "clipped" in encoded.lower()
    height = spec.get("height") or 0
    assert height >= 22 * 2


def test_heatmap_fixed_domains() -> None:
    narrative = heatmap_chart(
        [
            {
                "ticker": "AAPL",
                "fiscal_period": "FY2025-Q1",
                "dimension": "margins",
                "narrative_level": 1.0,
                "divergence": False,
            }
        ],
        "narrative_level",
        center_zero=False,
    ).to_dict()
    gap = heatmap_chart(
        [
            {
                "ticker": "AAPL",
                "fiscal_period": "FY2025-Q1",
                "dimension": "margins",
                "gap": 0.5,
                "divergence": False,
            }
        ],
        "gap",
        center_zero=True,
    ).to_dict()

    def _color_domain(spec: dict) -> list | None:
        encoding = spec.get("encoding") or {}
        color = encoding.get("color") or {}
        scale = color.get("scale") or {}
        return scale.get("domain")

    assert _color_domain(narrative) == [-2.0, 2.0]
    assert _color_domain(gap) == [-3.0, 3.0]


def test_chart_builders_return_altair_specs() -> None:
    import altair as alt

    heat_rows = [
        {
            "ticker": "AAPL",
            "fiscal_period": "FY2025-Q1",
            "dimension": "margins",
            "narrative_level": 1.0,
            "quant_z": 0.2,
            "gap": 0.8,
            "divergence": True,
        }
    ]
    chart = heatmap_chart(heat_rows, "gap", center_zero=True)
    assert isinstance(chart, alt.Chart) or hasattr(chart, "to_dict")

    rank = ranked_bar_chart(
        [
            {
                "ticker": "AAPL",
                "mean_quant_z": 0.4,
                "latest_period": "FY2025-Q2",
                "quarters": 2,
            },
            {
                "ticker": "MSFT",
                "mean_quant_z": -0.1,
                "latest_period": "FY2025-Q2",
                "quarters": 1,
            },
        ],
        "mean_quant_z",
    )
    assert hasattr(rank, "to_dict")

    scatter = narrative_quant_scatter(
        [
            {
                "ticker": "AAPL",
                "fiscal_period": "FY2025-Q1",
                "dimension": "margins",
                "narrative_level": 1.0,
                "quant_z": 0.2,
                "gap": 0.8,
                "divergence": True,
            },
            {
                "ticker": "AAPL",
                "fiscal_period": "FY2025-Q1",
                "dimension": "demand",
                "narrative_level": 0.5,
                "quant_z": 0.6,
                "gap": -0.1,
                "divergence": False,
            },
        ]
    )
    assert hasattr(scatter, "to_dict")

    nvq_rows = [
        {
            "ticker": "AAPL",
            "fiscal_period": "FY2025-Q1",
            "calendar_quarter": "2024-Q4",
            "dimension": "margins",
            "narrative_level": 1.0,
            "quant_z": 0.2,
            "gap": 0.8,
            "divergence": True,
            "agreement": "Divergence",
            "agreement_flipped": True,
            "diverge_streak": 2,
            "align_streak": 0,
            "peer_gap_delta": 0.4,
        },
        {
            "ticker": "MSFT",
            "fiscal_period": "FY2025-Q1",
            "calendar_quarter": "2024-Q4",
            "dimension": "margins",
            "narrative_level": 0.5,
            "quant_z": 0.1,
            "gap": 0.4,
            "divergence": False,
            "agreement": "Aligned",
            "agreement_flipped": False,
            "diverge_streak": 0,
            "align_streak": 1,
            "peer_gap_delta": 0.0,
        },
    ]
    plotly_fig = narrative_quant_plotly(nvq_rows, color_by_company=True)
    assert plotly_fig.data and len(plotly_fig.data) >= 2
    traj = narrative_quant_trajectory_plotly(nvq_rows)
    assert traj.data and len(traj.data) >= 2

    pulse = overview_pulse_chart(
        [
            {
                "ticker": "AAPL",
                "fiscal_period": "FY2025-Q2",
                "gap": 1.2,
                "abs_gap": 1.2,
                "narrative_level": 1.0,
                "quant_z": -0.2,
                "quant_flagged": True,
                "incomplete": False,
            }
        ]
    )
    assert hasattr(pulse, "to_dict")


def test_sparse_dimension_does_not_flag_company_pulse() -> None:
    data = DashboardData.from_records(_sample_rows())
    cards = {row["ticker"]: row for row in data.latest_scorecards()}
    # AAPL sample has sparse_dimension on one quarter/dim — not a severe flag.
    assert cards["AAPL"]["quant_quality_flags"]
    assert cards["AAPL"]["quant_flagged"] is False
    assert "sparse_dimension" in cards["AAPL"]["quant_quality_flags"]


def test_dimension_heatmap_uses_calendar_quarter() -> None:
    rows = _sample_rows()
    for row in rows:
        row["period_end_calendar_quarter"] = {
            "FY2025-Q1": "2024-Q4",
            "FY2025-Q2": "2025-Q1",
        }.get(row["fiscal_period"], "2025-Q1")
    data = DashboardData.from_records(rows)
    heat = data.dimension_heatmap(tickers=["AAPL", "MSFT"], latest_periods=4)
    assert heat
    assert all(row.get("calendar_quarter") for row in heat)
    assert all(row.get("period") == row.get("calendar_quarter") for row in heat)
    chart = heatmap_chart(heat, "gap", center_zero=True)
    encoded = str(chart.to_dict())
    assert "period" in encoded


def test_heatmap_facet_builds() -> None:
    rows = [
        {
            "ticker": "AAPL",
            "fiscal_period": "FY2025-Q1",
            "dimension": "margins",
            "gap": 0.5,
            "divergence": False,
        },
        {
            "ticker": "MSFT",
            "fiscal_period": "FY2025-Q1",
            "dimension": "margins",
            "gap": -0.2,
            "divergence": True,
        },
    ]
    chart = heatmap_chart(rows, "gap", facet_by_company=True, center_zero=True)
    spec = chart.to_dict()
    assert "facet" in spec
