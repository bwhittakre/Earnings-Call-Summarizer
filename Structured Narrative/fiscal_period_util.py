#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Map LSEG PERENDDATE values to company-fiscal quarter labels (FYyyyy-Qn)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.market.quarter_end_mode import resolve_quarter_label_for_date  # noqa: E402


def company_fiscal_period(ticker: str, perend) -> str:
    """Convert a quarter-end date to the company's fiscal label."""
    if isinstance(perend, pd.Timestamp):
        target = perend.date()
    elif isinstance(perend, date):
        target = perend
    else:
        target = pd.Timestamp(perend).date()
    return resolve_quarter_label_for_date(ticker.strip().upper(), target)
