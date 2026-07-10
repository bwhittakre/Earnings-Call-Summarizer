#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Map LSEG PERENDDATE values to company-fiscal quarter labels (FYyyyy-Qn)."""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.market.quarter_end_mode import resolve_quarter_label_for_date  # noqa: E402

_QUARTER = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)


def company_fiscal_period(ticker: str, perend) -> str:
    """Convert a quarter-end date to the company's fiscal label."""
    if isinstance(perend, pd.Timestamp):
        target = perend.date()
    elif isinstance(perend, date):
        target = perend
    else:
        target = pd.Timestamp(perend).date()
    return resolve_quarter_label_for_date(ticker.strip().upper(), target)


def prior_fiscal_period(fiscal_period: str) -> str | None:
    m = _QUARTER.match(fiscal_period.strip().upper())
    if not m:
        return None
    year, quarter = int(m.group(1)), int(m.group(2))
    if quarter == 1:
        return f"FY{year - 1}-Q4"
    return f"FY{year}-Q{quarter - 1}"


def normalize_fiscal_period(fiscal_period: str) -> str:
    m = _QUARTER.match(fiscal_period.strip().upper())
    if not m:
        raise ValueError(f"Invalid fiscal period label: {fiscal_period!r}")
    return f"FY{m.group(1)}-Q{m.group(2)}"
