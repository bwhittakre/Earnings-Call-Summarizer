#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Per-ticker registry of scored fiscal quarters for incremental pipeline runs.

Persisted at output/{TICKER}/json/quarter_registry.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from output_paths import company_artifact, resolve_read


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def registry_path(ticker: str):
    return company_artifact(ticker.upper(), "json", "quarter_registry", "json", mkdir=False)


def load_registry(ticker: str) -> dict[str, Any]:
    path = resolve_read(ticker, "quarter_registry", "json", layer="json")
    if path is None:
        return {
            "ticker": ticker.upper(),
            "scored_quarters": {},
            "prior_only_quarters": [],
            "updated_at": None,
        }
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(ticker: str, registry: dict[str, Any]) -> None:
    registry["ticker"] = ticker.upper()
    registry["updated_at"] = _now()
    out = company_artifact(ticker, "json", "quarter_registry", "json", mkdir=True)
    out.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def quarter_record(registry: dict[str, Any], fiscal_period: str) -> dict[str, Any]:
    return registry.setdefault("scored_quarters", {}).setdefault(fiscal_period, {})


def is_quarter_complete(registry: dict[str, Any], fiscal_period: str) -> bool:
    rec = registry.get("scored_quarters", {}).get(fiscal_period, {})
    base = all(rec.get(k) for k in ("dimensions_scored_at", "delta_scored_at", "surprise_scored_at"))
    if not base:
        return False
    any_novelty = any(
        r.get("novelty_scored_at")
        for r in registry.get("scored_quarters", {}).values()
    )
    if any_novelty:
        return bool(rec.get("novelty_scored_at"))
    return True


def has_dimensions(registry: dict[str, Any], fiscal_period: str) -> bool:
    rec = registry.get("scored_quarters", {}).get(fiscal_period, {})
    return bool(rec.get("dimensions_scored_at"))


def has_delta(registry: dict[str, Any], fiscal_period: str) -> bool:
    """True when delta for transition ending in *fiscal_period* is scored."""
    rec = registry.get("scored_quarters", {}).get(fiscal_period, {})
    return bool(rec.get("delta_scored_at"))


def has_surprise(registry: dict[str, Any], fiscal_period: str) -> bool:
    rec = registry.get("scored_quarters", {}).get(fiscal_period, {})
    return bool(rec.get("surprise_scored_at"))


def has_novelty(registry: dict[str, Any], fiscal_period: str) -> bool:
    rec = registry.get("scored_quarters", {}).get(fiscal_period, {})
    return bool(rec.get("novelty_scored_at"))


def ensure_registry(ticker: str, *, model: str = "unknown") -> dict[str, Any]:
    """Load registry and merge any missing quarter marks from existing view JSON."""
    return sync_registry_from_views(ticker, model=model)


def mark_dimensions(ticker: str, fiscal_period: str, *, model: str, as_of_date: str | None = None) -> None:
    reg = load_registry(ticker)
    rec = quarter_record(reg, fiscal_period)
    rec["dimensions_scored_at"] = _now()
    rec["model"] = model
    if as_of_date:
        rec["as_of_date"] = as_of_date
    save_registry(ticker, reg)


def mark_delta(ticker: str, fiscal_period: str) -> None:
    reg = load_registry(ticker)
    quarter_record(reg, fiscal_period)["delta_scored_at"] = _now()
    save_registry(ticker, reg)


def mark_surprise(ticker: str, fiscal_period: str) -> None:
    reg = load_registry(ticker)
    quarter_record(reg, fiscal_period)["surprise_scored_at"] = _now()
    save_registry(ticker, reg)


def mark_novelty(ticker: str, fiscal_period: str) -> None:
    reg = load_registry(ticker)
    quarter_record(reg, fiscal_period)["novelty_scored_at"] = _now()
    save_registry(ticker, reg)


def set_prior_only(ticker: str, fiscal_periods: list[str]) -> None:
    reg = load_registry(ticker)
    reg["prior_only_quarters"] = list(fiscal_periods)
    save_registry(ticker, reg)


def sync_registry_from_views(ticker: str, *, model: str = "unknown") -> dict[str, Any]:
    """Bootstrap registry from existing dimension/delta/surprise view JSON if present."""
    from output_paths import resolve_read as _resolve

    reg = load_registry(ticker)
    dim_view_path = _resolve(ticker, "dimension_view", "json", layer="json")
    if dim_view_path:
        dim_view = json.loads(dim_view_path.read_text(encoding="utf-8"))
        for q in dim_view.get("quarters", []):
            fp = q["fiscal_period"]
            if q.get("prior_only"):
                prior = set(reg.get("prior_only_quarters", []))
                prior.add(fp)
                reg["prior_only_quarters"] = sorted(prior)
            if q.get("prior_only") and not q.get("output_scope", True):
                rec = quarter_record(reg, fp)
                rec.setdefault("dimensions_scored_at", _now())
                rec.setdefault("model", model)
                if q.get("as_of_date"):
                    rec.setdefault("as_of_date", q["as_of_date"])
                continue
            if not q.get("output_scope", True):
                continue
            rec = quarter_record(reg, fp)
            rec.setdefault("dimensions_scored_at", _now())
            rec.setdefault("model", model)
            if q.get("as_of_date"):
                rec.setdefault("as_of_date", q["as_of_date"])

    delta_path = _resolve(ticker, "delta_view", "json", layer="json")
    if delta_path:
        delta_view = json.loads(delta_path.read_text(encoding="utf-8"))
        for tr in delta_view.get("transitions", []):
            fp = tr["fiscal_period"]
            quarter_record(reg, fp).setdefault("delta_scored_at", _now())

    surprise_path = _resolve(ticker, "surprise_view", "json", layer="json")
    if surprise_path:
        surprise_view = json.loads(surprise_path.read_text(encoding="utf-8"))
        for q in surprise_view.get("quarters", []):
            fp = q["fiscal_period"]
            quarter_record(reg, fp).setdefault("surprise_scored_at", _now())

    novelty_path = _resolve(ticker, "novelty_view", "json", layer="json")
    if novelty_path:
        novelty_view = json.loads(novelty_path.read_text(encoding="utf-8"))
        for q in novelty_view.get("quarters", []):
            fp = q["fiscal_period"]
            quarter_record(reg, fp).setdefault("novelty_scored_at", _now())

    save_registry(ticker, reg)
    return reg
