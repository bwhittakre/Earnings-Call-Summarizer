#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AMZN FY2024 pilot scope — superseded by company_config for multi-ticker runs."""
from __future__ import annotations

from company_config import DEFAULT_TICKER, get_company

# Backward-compatible defaults (AMZN FY2025 multi-company pilot).
_company = get_company(DEFAULT_TICKER)

TICKER = _company.ticker
COMPANY_NAME = _company.company_name
OUTPUT_QUARTERS = list(_company.output_quarters)
PRIOR_QUARTERS = list(_company.prior_quarters)


def scoring_quarters(ticker: str | None = None) -> list[str]:
    return get_company(ticker).scoring_quarters()


def is_output_quarter(fiscal_period: str, ticker: str | None = None) -> bool:
    return get_company(ticker).is_output_quarter(fiscal_period)


def is_prior_only(fiscal_period: str, ticker: str | None = None) -> bool:
    return get_company(ticker).is_prior_only(fiscal_period)
