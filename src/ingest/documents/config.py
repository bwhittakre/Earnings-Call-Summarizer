from __future__ import annotations

from pathlib import Path

import yaml

from src.ingest.documents.models import DocumentFetchError

DEFAULT_DOCUMENT_SOURCES_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "config"
    / "document_sources.yaml"
)


def load_document_sources(path: Path = DEFAULT_DOCUMENT_SOURCES_PATH) -> dict:
    if not path.exists():
        raise DocumentFetchError(f"Document sources config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DocumentFetchError(f"Invalid document sources config: {path}")
    return data


def resolve_ticker_config(ticker: str, path: Path = DEFAULT_DOCUMENT_SOURCES_PATH) -> dict:
    config = load_document_sources(path)
    key = ticker.strip().upper()
    if key not in config:
        raise DocumentFetchError(
            f"Ticker {key} not configured in {path}. Add CIK and optional ir_provider."
        )
    entry = config[key]
    if not isinstance(entry, dict) or not entry.get("cik"):
        raise DocumentFetchError(f"Ticker {key} missing required 'cik' in {path}")
    return entry
