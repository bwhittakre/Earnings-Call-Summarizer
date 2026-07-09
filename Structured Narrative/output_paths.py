#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Central output path layout: output/{TICKER}/{layer}/..."""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / "output"
CROSS_DIR = ROOT / "cross_company"

LAYERS = ("parquet", "workbooks", "csv", "json", "reports", "audit")


def _norm_ticker(ticker: str) -> str:
    return ticker.strip().upper()


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
    """Layered path first, then legacy flat output/{TICKER}_{stem}.{ext}."""
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


def cross_company_artifact(stem: str, ext: str, *, mkdir: bool = False) -> Path:
    ext = ext.lstrip(".")
    if mkdir:
        CROSS_DIR.mkdir(parents=True, exist_ok=True)
    return CROSS_DIR / f"{stem}.{ext}"
