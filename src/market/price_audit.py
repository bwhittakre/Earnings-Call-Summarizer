from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from src.ingest.call_date import format_call_date
from src.market.models import QuarterEndPrice
from src.paths import OUTPUT_ROOT

PRICE_AUDIT_DIR = OUTPUT_ROOT / "price_audit"


def save_price_audit(
    label: str,
    ticker: str,
    prices: list[QuarterEndPrice],
    *,
    call_date: date,
    reported_quarter: str,
    prior_labels: list[str],
    mode: str = "default",
    strict: bool = False,
    adjusted: bool = True,
) -> Path:
    PRICE_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = re.sub(r"[^\w\-]+", "_", label)
    path = PRICE_AUDIT_DIR / f"{safe_label}_{timestamp}.json"
    path.write_text(
        json.dumps(
            {
                "label": label,
                "ticker": ticker,
                "call_date": format_call_date(call_date),
                "as_of_date": call_date.isoformat(),
                "reported_quarter": reported_quarter,
                "prior_labels": prior_labels,
                "mode": mode,
                "strict": strict,
                "adjusted": adjusted,
                "fetched_at": timestamp,
                "prices": [
                    {
                        "quarter_label": price.quarter_label,
                        "quarter_end_date": price.quarter_end_date.isoformat(),
                        "price_date": price.price_date.isoformat(),
                        "adjusted_close": price.adjusted_close,
                        "cap_applied": (
                            price.cap_applied.isoformat()
                            if price.cap_applied
                            else min(price.quarter_end_date, call_date).isoformat()
                        ),
                    }
                    for price in prices
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
