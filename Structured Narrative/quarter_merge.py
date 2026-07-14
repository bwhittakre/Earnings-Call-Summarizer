#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers for partial quarter re-runs that merge into existing outputs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from fiscal_period_util import fiscal_period_sort_key
from output_paths import company_artifact, resolve_read, resolve_read_parquet_or_csv


def norm_quarters(quarters: list[str] | None) -> set[str] | None:
    if not quarters:
        return None
    return {q.strip().upper() for q in quarters}


def merge_rows_by_period(
    existing: list[dict],
    new: list[dict],
    periods: set[str],
    *,
    period_key: str = "fiscal_period",
) -> list[dict]:
    kept = [r for r in existing if str(r.get(period_key)) not in periods]
    return kept + new


def merge_quarter_views(
    existing: list[dict],
    new: list[dict],
    periods: set[str],
    *,
    period_key: str = "fiscal_period",
) -> list[dict]:
    kept = [q for q in existing if str(q.get(period_key)) not in periods]
    order = [str(q.get(period_key)) for q in existing + new]
    merged = kept + new
    seen: set[str] = set()
    out: list[dict] = []
    for fp in order:
        if fp in seen:
            continue
        for q in merged:
            if str(q.get(period_key)) == fp:
                out.append(q)
                seen.add(fp)
                break
    for q in merged:
        fp = str(q.get(period_key))
        if fp not in seen:
            out.append(q)
            seen.add(fp)
    return sorted(out, key=lambda q: fiscal_period_sort_key(str(q.get(period_key))))


def merge_transitions(
    existing: list[dict],
    new: list[dict],
    current_periods: set[str],
    *,
    current_key: str = "fiscal_period",
) -> list[dict]:
    kept = [t for t in existing if str(t.get(current_key)) not in current_periods]
    return kept + new


def load_csv_rows(ticker: str, stem: str) -> list[dict]:
    path = resolve_read(ticker, stem, "csv", layer="csv")
    if path is None:
        flat = Path(__file__).resolve().parent / "output" / f"{ticker.upper()}_{stem}.csv"
        if not flat.exists():
            return []
        path = flat
    return pd.read_csv(path).to_dict("records")


def load_json_obj(ticker: str, stem: str) -> dict | None:
    path = resolve_read(ticker, stem, "json", layer="json")
    if path is None:
        flat = Path(__file__).resolve().parent / "output" / f"{ticker.upper()}_{stem}.json"
        if not flat.exists():
            return None
        path = flat
    return json.loads(path.read_text(encoding="utf-8"))


def load_parquet_df(ticker: str, stem: str) -> pd.DataFrame | None:
    path = resolve_read_parquet_or_csv(ticker, stem, layer="parquet")
    if path is None:
        return None
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)


def merge_dataframes_by_period(
    existing: pd.DataFrame | None,
    new: pd.DataFrame,
    periods: set[str],
    *,
    period_key: str = "fiscal_period",
) -> pd.DataFrame:
    if existing is None or existing.empty:
        return new
    kept = existing[~existing[period_key].astype(str).isin(periods)]
    return pd.concat([kept, new], ignore_index=True)
