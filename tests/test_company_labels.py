from services.earnings_monitor.dashboard.company_labels import (
    company_brand,
    format_company_label,
    with_company_labels,
)


def test_format_company_label_includes_brand() -> None:
    assert format_company_label("AAPL") == "AAPL (Apple)"
    assert format_company_label("msft") == "MSFT (Microsoft)"
    assert format_company_label("MU") == "MU (Micron)"


def test_ibm_stays_ticker_only_when_brand_matches() -> None:
    assert company_brand("IBM") is None
    assert format_company_label("IBM") == "IBM"


def test_unknown_ticker_falls_back_to_code() -> None:
    assert format_company_label("ZZZZ") == "ZZZZ"


def test_with_company_labels_adds_column() -> None:
    rows = with_company_labels([{"ticker": "AAPL", "fiscal_period": "FY2026-Q3"}])
    assert rows[0]["company"] == "AAPL (Apple)"
    assert rows[0]["ticker"] == "AAPL"
