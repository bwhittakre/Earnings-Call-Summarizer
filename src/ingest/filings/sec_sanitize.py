from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

from src.ingest.text_clean import clean_text

EDGAR_MARKER_RE = re.compile(
    r"(?:<SEC-DOCUMENT>|<TYPE>\s*(?:10-[KQ]|8-K|S-1))",
    re.IGNORECASE,
)
TEXT_BLOCK_RE = re.compile(r"<TEXT>(.*?)</TEXT>", re.IGNORECASE | re.DOTALL)
XBRL_TAG_RE = re.compile(
    r"<ix:[^>]+>.*?</ix:[^>]+>|<ix:[^/>]+/>",
    re.IGNORECASE | re.DOTALL,
)
XBRL_NAMESPACE_RE = re.compile(r"\bxbrli:[a-zA-Z0-9_-]+\b")
HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")


def looks_like_edgar_submission(text: str) -> bool:
    sample = text[:5000]
    return bool(EDGAR_MARKER_RE.search(sample))


def looks_like_html(text: str) -> bool:
    return bool(HTML_TAG_RE.search(text[:10000]))


def extract_edgar_text_blocks(raw: str) -> str:
    blocks = TEXT_BLOCK_RE.findall(raw)
    if blocks:
        return "\n\n".join(blocks)
    return raw


def strip_html_to_text(text: str) -> str:
    if not looks_like_html(text):
        return text
    soup = BeautifulSoup(text, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "meta", "link"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def strip_xbrl_noise(text: str) -> str:
    text = XBRL_TAG_RE.sub(" ", text)
    text = XBRL_NAMESPACE_RE.sub(" ", text)
    text = re.sub(r"\b\d{10,}\b", " ", text)
    return text


def sanitize_filing_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = html.unescape(text)
    if looks_like_edgar_submission(text):
        text = extract_edgar_text_blocks(text)
    if looks_like_html(text):
        text = strip_html_to_text(text)
    text = strip_xbrl_noise(text)
    return clean_text(text)
