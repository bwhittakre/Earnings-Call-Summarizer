#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Central output path layout.

Every artifact lives under ``output/{top_level}/{layer}/...``:

  * Per-company: ``output/{TICKER}/{parquet|workbooks|csv|json|reports|audit}/``
  * Cross-company: ``output/cross_company/{layer}/``
  * Shared (not tied to one ticker): ``output/shared/{bucket}/`` (e.g. transcripts)

If the correct *top-level* bucket is unclear, do **not** guess — write to
``output/{stem}.{ext}`` via :func:`uncertain_artifact` so misclassified files
stay visible at the output root.
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / "output"

# Cross-company output dir is independently overridable via
# SN_CROSS_COMPANY_OUTPUT_DIR. This exists so tests/tools can smoke-test
# build_consolidated_panel_report.py (or similar cross-company writers)
# WITHOUT touching the real shared deliverable at
# output/cross_company/reports/consolidated_feature_panel.html — a mistake
# that previously caused that report to be silently overwritten with
# narrow/partial ticker data (e.g. MSFT-only) every time the full test suite
# ran. Left unset, behavior is unchanged.
_CROSS_DIR_OVERRIDE = os.environ.get("SN_CROSS_COMPANY_OUTPUT_DIR")
CROSS_DIR = Path(_CROSS_DIR_OVERRIDE) if _CROSS_DIR_OVERRIDE else ROOT / "cross_company"
SHARED_DIR = ROOT / "shared"

LAYERS = ("parquet", "workbooks", "csv", "json", "reports", "audit")
SHARED_BUCKETS = ("transcripts",)
RESERVED_TOP_LEVEL = frozenset({"cross_company", "shared"})

# Legacy flat cache before shared/transcripts/ existed.
LEGACY_TRANSCRIPT_DIR = ROOT / "transcripts"


def _norm_ticker(ticker: str) -> str:
    return ticker.strip().upper()


# ── Per-company ───────────────────────────────────────────────────────────────


def company_root(ticker: str, *, mkdir: bool = False) -> Path:
    path = ROOT / _norm_ticker(ticker)
    if mkdir:
        path.mkdir(parents=True, exist_ok=True)
    return path


def company_layer(ticker: str, layer: str, *, mkdir: bool = False) -> Path:
    if layer not in LAYERS:
        raise ValueError(f"Unknown layer {layer!r}. Expected one of {LAYERS}.")
    path = company_root(ticker, mkdir=mkdir) / layer
    if mkdir:
        path.mkdir(parents=True, exist_ok=True)
    return path


def company_artifact(ticker: str, layer: str, stem: str, ext: str, *, mkdir: bool = False) -> Path:
    ext = ext.lstrip(".")
    return company_layer(ticker, layer, mkdir=mkdir) / f"{stem}.{ext}"


def ensure_company_tree(ticker: str) -> Path:
    root = company_root(ticker, mkdir=True)
    for layer in LAYERS:
        company_layer(ticker, layer, mkdir=True)
    return root


def legacy_flat_file(ticker: str, stem: str, ext: str) -> Path:
    ext = ext.lstrip(".")
    t = _norm_ticker(ticker)
    return ROOT / f"{t}_{stem}.{ext}"


def resolve_read(ticker: str, stem: str, ext: str, *, layer: str) -> Path | None:
    """Layered path first, then legacy flat ``output/{TICKER}_{stem}.{ext}``."""
    ext = ext.lstrip(".")
    layered = company_artifact(ticker, layer, stem, ext)
    if layered.exists():
        return layered
    legacy = legacy_flat_file(ticker, stem, ext)
    if legacy.exists():
        return legacy
    return None


def resolve_read_parquet_or_csv(ticker: str, stem: str, *, layer: str = "parquet") -> Path | None:
    for ext in ("parquet", "csv"):
        found = resolve_read(ticker, stem, ext, layer=layer)
        if found is not None:
            return found
    return None


def resolve_read_required(ticker: str, stem: str, ext: str, *, layer: str) -> Path:
    found = resolve_read(ticker, stem, ext, layer=layer)
    if found is None:
        t = _norm_ticker(ticker)
        raise FileNotFoundError(
            f"Missing {layer}/{stem}.{ext} for {t} "
            f"(also checked legacy {t}_{stem}.{ext})."
        )
    return found


def list_company_tickers() -> list[str]:
    """Top-level dirs under output/ that look like ticker folders."""
    if not ROOT.is_dir():
        return []
    return sorted(
        p.name
        for p in ROOT.iterdir()
        if p.is_dir() and p.name not in RESERVED_TOP_LEVEL and not p.name.startswith("_")
    )


# ── Cross-company ─────────────────────────────────────────────────────────────


def cross_company_layer(layer: str, *, mkdir: bool = False) -> Path:
    if layer not in LAYERS:
        raise ValueError(f"Unknown layer {layer!r}. Expected one of {LAYERS}.")
    path = CROSS_DIR / layer
    if mkdir:
        path.mkdir(parents=True, exist_ok=True)
    return path


def cross_company_artifact(layer: str, stem: str, ext: str, *, mkdir: bool = False) -> Path:
    ext = ext.lstrip(".")
    return cross_company_layer(layer, mkdir=mkdir) / f"{stem}.{ext}"


def ensure_cross_company_tree() -> Path:
    CROSS_DIR.mkdir(parents=True, exist_ok=True)
    for layer in LAYERS:
        cross_company_layer(layer, mkdir=True)
    return CROSS_DIR


def legacy_cross_company_flat(stem: str, ext: str) -> Path:
    """Flat file directly under cross_company/ (pre-layer layout)."""
    ext = ext.lstrip(".")
    return CROSS_DIR / f"{stem}.{ext}"


def legacy_cross_company_root(stem: str, ext: str) -> Path:
    """Very old flat file at output root with cross_company_ prefix."""
    ext = ext.lstrip(".")
    return ROOT / f"cross_company_{stem}.{ext}"


def resolve_read_cross(stem: str, ext: str, *, layer: str) -> Path | None:
    """Layered cross-company path, then legacy flat locations."""
    ext = ext.lstrip(".")
    layered = cross_company_artifact(layer, stem, ext)
    if layered.exists():
        return layered
    legacy_dir = legacy_cross_company_flat(stem, ext)
    if legacy_dir.exists():
        return legacy_dir
    legacy_root = legacy_cross_company_root(stem, ext)
    if legacy_root.exists():
        return legacy_root
    return None


def resolve_read_cross_parquet_or_csv(stem: str, *, layer: str = "parquet") -> Path | None:
    for ext in ("parquet", "csv"):
        found = resolve_read_cross(stem, ext, layer=layer)
        if found is not None:
            return found
    return None


# ── Shared (global cache, not company-specific) ───────────────────────────────


def shared_layer(bucket: str, *, mkdir: bool = False) -> Path:
    if bucket not in SHARED_BUCKETS:
        raise ValueError(f"Unknown shared bucket {bucket!r}. Expected one of {SHARED_BUCKETS}.")
    path = SHARED_DIR / bucket
    if mkdir:
        path.mkdir(parents=True, exist_ok=True)
    return path


def shared_artifact(bucket: str, stem: str, ext: str, *, mkdir: bool = False) -> Path:
    ext = ext.lstrip(".")
    return shared_layer(bucket, mkdir=mkdir) / f"{stem}.{ext}"


def ensure_shared_tree() -> Path:
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    for bucket in SHARED_BUCKETS:
        shared_layer(bucket, mkdir=True)
    return SHARED_DIR


def resolve_transcript_cache(ticker: str, fiscal_period: str) -> Path | None:
    """New shared/transcripts path, then legacy output/transcripts/."""
    stem = f"{_norm_ticker(ticker)}_{fiscal_period}"
    layered = shared_artifact("transcripts", stem, "json")
    if layered.exists():
        return layered
    legacy = LEGACY_TRANSCRIPT_DIR / f"{stem}.json"
    if legacy.exists():
        return legacy
    return None


def transcript_cache_path(ticker: str, fiscal_period: str, *, mkdir: bool = False) -> Path:
    """Write path for FMP transcript API cache."""
    stem = f"{_norm_ticker(ticker)}_{fiscal_period}"
    return shared_artifact("transcripts", stem, "json", mkdir=mkdir)


# ── Uncertain classification ──────────────────────────────────────────────────


def uncertain_artifact(stem: str, ext: str) -> Path:
    """Use when the top-level bucket (ticker vs cross_company vs shared) is unknown."""
    ext = ext.lstrip(".")
    return ROOT / f"{stem}.{ext}"
