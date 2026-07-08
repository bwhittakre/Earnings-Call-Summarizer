#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AMZN FY2024 pilot scope — FY2023-Q4 is prior-only for Q1 delta baseline."""
from __future__ import annotations

TICKER = "AMZN"
COMPANY_NAME = "Amazon.com, Inc."

OUTPUT_QUARTERS = [
    "FY2024-Q1",
    "FY2024-Q2",
    "FY2024-Q3",
    "FY2024-Q4",
]

PRIOR_QUARTERS = [
    "FY2023-Q4",  # scored for delta baseline; excluded from published CSV/HTML outputs
]


def scoring_quarters() -> list[str]:
    return PRIOR_QUARTERS + OUTPUT_QUARTERS


def is_output_quarter(fiscal_period: str) -> bool:
    return fiscal_period in OUTPUT_QUARTERS


def is_prior_only(fiscal_period: str) -> bool:
    return fiscal_period in PRIOR_QUARTERS
