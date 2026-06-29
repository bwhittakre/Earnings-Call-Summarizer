from __future__ import annotations

import re

from bs4 import BeautifulSoup

from src.ingest.parsers import clean_text


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return clean_text(strip_ixbrl_tags(text))


def strip_ixbrl_tags(text: str) -> str:
    text = re.sub(r"<ix:[^>]+>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</ix:[^>]+>", "", text, flags=re.IGNORECASE)
    return text
