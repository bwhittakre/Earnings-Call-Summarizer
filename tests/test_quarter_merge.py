from pathlib import Path
import sys

SN = Path(__file__).resolve().parents[1] / "Structured Narrative"
sys.path.insert(0, str(SN))

from quarter_merge import chronological_quarters  # noqa: E402


def test_newest_first_view_pairs_chronologically():
    quarters = [
        {"fiscal_period": "FY2026-Q2"},
        {"fiscal_period": "FY2026-Q1"},
        {"fiscal_period": "FY2025-Q4"},
    ]
    ordered = chronological_quarters(quarters)
    assert [q["fiscal_period"] for q in ordered] == [
        "FY2025-Q4",
        "FY2026-Q1",
        "FY2026-Q2",
    ]
    pairs = [
        (ordered[i - 1]["fiscal_period"], ordered[i]["fiscal_period"])
        for i in range(1, len(ordered))
    ]
    assert pairs == [("FY2025-Q4", "FY2026-Q1"), ("FY2026-Q1", "FY2026-Q2")]
