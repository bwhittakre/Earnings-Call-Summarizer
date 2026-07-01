from __future__ import annotations

from pathlib import Path

import fitz

from src.ingest.filings.sec_sanitize import sanitize_filing_text

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".html", ".htm"}


def parse_txt(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return sanitize_filing_text(raw)


def parse_pdf(path: Path) -> str:
    doc = fitz.open(path)
    try:
        pages = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    return sanitize_filing_text("\n".join(pages))


def parse_html(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return sanitize_filing_text(raw)


def parse_transcript(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".txt":
        return parse_txt(path)
    if ext == ".pdf":
        return parse_pdf(path)
    if ext in {".html", ".htm"}:
        return parse_html(path)
    raise ValueError(f"Unsupported file type: {ext}")
