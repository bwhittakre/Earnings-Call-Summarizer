from __future__ import annotations

import re
from dataclasses import dataclass

from src.ingest.filings.types import DocumentType

ITEM_HEADER_RE = re.compile(
    r"(?:(?:^|\n)\s*)Item\s+(\d+[A-Z]?)\.\s*([^\n]{0,120})",
    re.IGNORECASE,
)
EIGHT_K_ITEM_RE = re.compile(
    r"(?:(?:^|\n)\s*)Item\s+(\d+\.\d+)\.\s*([^\n]{0,120})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SecSection:
    item_id: str
    title: str
    text: str


def _split_by_item_headers(text: str, pattern: re.Pattern[str]) -> list[SecSection]:
    matches = list(pattern.finditer(text))
    if not matches:
        return [SecSection(item_id="full", title="Full document", text=text.strip())]

    sections: list[SecSection] = []
    for index, match in enumerate(matches):
        item_id = match.group(1).upper()
        title = match.group(2).strip()
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append(SecSection(item_id=item_id, title=title, text=body))
    return sections


def extract_sections(text: str, doc_type: DocumentType) -> list[SecSection]:
    if doc_type == DocumentType.EIGHT_K:
        sections = _split_by_item_headers(text, EIGHT_K_ITEM_RE)
        if len(sections) == 1 and sections[0].item_id == "full":
            return sections
        return sections

    return _split_by_item_headers(text, ITEM_HEADER_RE)


def select_sections_for_doc(
    text: str,
    doc_type: DocumentType,
    *,
    is_prior_quarter_ten_q: bool = False,
) -> list[SecSection]:
    all_sections = extract_sections(text, doc_type)

    if doc_type in {
        DocumentType.PRESS_RELEASE,
        DocumentType.INVESTOR_PRESENTATION,
    }:
        return all_sections

    if doc_type == DocumentType.EIGHT_K:
        if len(text) <= 80_000:
            return [SecSection(item_id="full", title="Full 8-K", text=text)]
        preferred = {"2.02", "7.01", "2.05", "8.01"}
        picked = [section for section in all_sections if section.item_id in preferred]
        return picked or all_sections[:3] or all_sections

    if doc_type == DocumentType.TEN_Q:
        if is_prior_quarter_ten_q:
            wanted = {"2", "1"}
        else:
            wanted = {"2", "1A", "1"}
        return _pick_items(all_sections, wanted, text)

    if doc_type == DocumentType.TEN_K:
        wanted = {"7", "1A", "1"}
        return _pick_items(all_sections, wanted, text)

    return all_sections


def _pick_items(
    sections: list[SecSection],
    wanted_ids: set[str],
    fallback_text: str,
) -> list[SecSection]:
    picked = [section for section in sections if section.item_id in wanted_ids]
    if picked:
        return picked
    if len(sections) == 1 and sections[0].item_id == "full":
        return sections
    return [SecSection(item_id="full", title="Full document", text=fallback_text)]
