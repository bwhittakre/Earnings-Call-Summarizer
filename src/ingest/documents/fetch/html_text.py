from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from src.ingest.parsers import clean_text

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def _table_to_text(table) -> str:
    rows: list[str] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        row_text = " | ".join(cell.get_text(" ", strip=True) for cell in cells)
        if row_text.strip():
            rows.append(row_text)
    return "\n".join(rows)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    for table in soup.find_all("table"):
        table_text = _table_to_text(table)
        if table_text.strip():
            table.replace_with(f"\n{table_text}\n")
        else:
            table.decompose()

    text = soup.get_text(separator="\n")
    return clean_text(strip_ixbrl_tags(text))


def strip_ixbrl_tags(text: str) -> str:
    text = re.sub(r"<ix:[^>]+>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</ix:[^>]+>", "", text, flags=re.IGNORECASE)
    return text
