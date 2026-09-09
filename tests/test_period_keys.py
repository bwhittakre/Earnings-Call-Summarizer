"""FY vs conference period identity. No LLM."""
from datetime import date

from services.earnings_monitor.period_keys import (
    call_chrono_key,
    canonical_period,
    period_kind,
    period_sort_key,
    seed_before_call,
)


def test_period_kind_and_canonical() -> None:
    assert period_kind("FY2025-Q3") == "fy"
    assert period_kind("CONF-2025-08-27") == "conf"
    assert canonical_period("CONF-2025-08-27") == "FY2025-Q3"
    assert canonical_period("FY2026-Q2") == "FY2026-Q2"


def test_period_sort_puts_fy_before_conf() -> None:
    periods = ["CONF-2025-08-27", "FY2025-Q3", "CONF-2026-03-04", "FY2026-Q1"]
    ordered = sorted(periods, key=period_sort_key)
    assert ordered == ["FY2025-Q3", "FY2026-Q1", "CONF-2025-08-27", "CONF-2026-03-04"]


def test_call_chrono_interleaves_fy_and_conf() -> None:
    periods = [
        "CONF-2026-09-08",
        "FY2025-Q3",
        "CONF-2025-08-27",
        "FY2026-Q2",
        "FY2025-Q1",
    ]
    ordered = sorted(periods, key=call_chrono_key)
    assert ordered == [
        "FY2025-Q1",
        "CONF-2025-08-27",
        "FY2025-Q3",
        "FY2026-Q2",
        "CONF-2026-09-08",
    ]
    assert call_chrono_key("CONF-2025-08-27") == date(2025, 8, 27)
    assert call_chrono_key("FY2025-Q3") == date(2025, 9, 30)


def test_seed_before_call() -> None:
    assert seed_before_call("CONF-2025-08-27", "CONF-2026-03-04") is True
    assert seed_before_call("CONF-2026-03-04", "CONF-2025-08-27") is False
    assert seed_before_call("FY2025-Q2", "CONF-2025-08-27") is True
    assert seed_before_call("FY2025-Q3", "FY2026-Q1") is True
    assert seed_before_call("FY2026-Q1", "FY2026-Q1") is False
