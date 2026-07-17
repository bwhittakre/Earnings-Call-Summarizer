#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-section coverage / exclusion tracking for consolidated panels."""
from __future__ import annotations

from typing import Any

import pandas as pd

from quarter_registry import is_quarter_complete, load_registry


def annotate_included(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.copy()
    df["in_cross_section"] = True
    df["exclusion_reason"] = None
    return df


def build_coverage_summary(
    *,
    tickers_requested: list[str],
    tickers_loaded: list[str],
    tickers_skipped: list[str],
    quarter_scope: list[str] | None,
    stacked: pd.DataFrame,
) -> dict[str, Any]:
    """Per-ticker scored vs included quarters with exclusion reasons."""
    scope_set = {q.upper() for q in (quarter_scope or [])}
    by_ticker: dict[str, Any] = {}

    for ticker in tickers_requested:
        t = ticker.upper()
        entry: dict[str, Any] = {
            "loaded": t in tickers_loaded,
            "scored_complete": [],
            "included": [],
            "excluded": [],
        }
        if t in tickers_skipped and t not in tickers_loaded:
            if t not in {x.upper() for x in tickers_loaded}:
                # distinguish missing panel vs empty after filter
                pass

        try:
            reg = load_registry(t)
        except Exception:
            entry["excluded"].append(
                {"fiscal_period": None, "reason": "missing_feature_panel"}
            )
            by_ticker[t] = entry
            continue

        prior_only = {str(q).upper() for q in reg.get("prior_only_quarters", [])}
        scored = sorted(reg.get("scored_quarters", {}).keys())
        for fp in scored:
            fp_u = str(fp).upper()
            complete = is_quarter_complete(reg, fp) and fp_u not in prior_only
            if complete:
                entry["scored_complete"].append(fp_u)

            if not complete:
                reason = "prior_only" if fp_u in prior_only else "registry_incomplete"
                entry["excluded"].append({"fiscal_period": fp_u, "reason": reason})
                continue
            if scope_set and fp_u not in scope_set:
                entry["excluded"].append(
                    {"fiscal_period": fp_u, "reason": "outside_quarter_scope"}
                )
                continue
            entry["included"].append(fp_u)

        if t not in tickers_loaded:
            if not entry["excluded"]:
                entry["excluded"].append(
                    {"fiscal_period": None, "reason": "missing_feature_panel"}
                )
            elif t in {s.upper() for s in tickers_skipped}:
                # empty after scope — ensure reason present for scored-complete outside scope
                if entry["scored_complete"] and not any(
                    e.get("reason") == "outside_quarter_scope" for e in entry["excluded"]
                ):
                    entry["excluded"].append(
                        {"fiscal_period": None, "reason": "not_in_ticker_list"}
                    )

        if "ticker" in stacked.columns:
            included_from_data = sorted(
                stacked.loc[stacked["ticker"].astype(str).str.upper() == t, "fiscal_period"]
                .dropna()
                .astype(str)
                .str.upper()
                .unique()
                .tolist()
            )
            if included_from_data:
                entry["included"] = included_from_data

        by_ticker[t] = entry

    # Tickers never requested but useful for diagnostics: none

    return {
        "tickers_requested": [t.upper() for t in tickers_requested],
        "tickers_loaded": [t.upper() for t in tickers_loaded],
        "tickers_skipped": [t.upper() for t in tickers_skipped],
        "quarter_scope": sorted(scope_set) if scope_set else None,
        "by_ticker": by_ticker,
    }


def mark_not_in_ticker_list(tickers_not_loaded: list[str]) -> list[dict[str, str]]:
    return [
        {"ticker": t.upper(), "fiscal_period": "", "reason": "not_in_ticker_list"}
        for t in tickers_not_loaded
    ]
