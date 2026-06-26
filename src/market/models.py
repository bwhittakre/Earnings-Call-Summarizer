from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class QuarterEndPrice:
    quarter_label: str
    quarter_end_date: date
    price_date: date
    adjusted_close: float
    ticker: str

    def format_line(self) -> str:
        return (
            f"{self.quarter_label} end ({self.quarter_end_date.isoformat()}, "
            f"traded {self.price_date.isoformat()}): ${self.adjusted_close:.2f}"
        )
