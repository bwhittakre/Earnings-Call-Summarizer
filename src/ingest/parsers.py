from __future__ import annotations

import re
from pathlib import Path

import fitz
from bs4 import BeautifulSoup

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".html", ".htm"}


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_txt(path: Path) -> str:
    return clean_text(path.read_text(encoding="utf-8", errors="replace"))


def parse_pdf(path: Path) -> str:
    doc = fitz.open(path)
    try:
        pages = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    return clean_text("\n".join(pages))


def parse_html(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return clean_text(soup.get_text(separator="\n"))


def parse_transcript(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".txt":
        return parse_txt(path)
    if ext == ".pdf":
        return parse_pdf(path)
    if ext in {".html", ".htm"}:
        return parse_html(path)
    raise ValueError(f"Unsupported file type: {ext}")
