from __future__ import annotations

import re
from pathlib import Path

from src.ingest.filings.types import DOCUMENT_BASENAMES, DocumentType, LoadedDocument
from src.ingest.parsers import SUPPORTED_EXTENSIONS, parse_transcript

EIGHT_K_STEM_PATTERN = re.compile(r"^8-[Kk](?:[_\-.](.+))?$")
EIGHT_K_SUBFOLDER_NAMES = ("8-K", "8-k")


def find_document_path(folder: Path, basenames: tuple[str, ...]) -> Path | None:
    for basename in basenames:
        for ext in sorted(SUPPORTED_EXTENSIONS):
            candidate = folder / f"{basename}{ext}"
            if candidate.is_file():
                return candidate
    return None


def _is_eight_k_filename(path: Path) -> bool:
    return bool(EIGHT_K_STEM_PATTERN.match(path.stem))


def eight_k_section_label(path: Path) -> str | None:
    match = EIGHT_K_STEM_PATTERN.match(path.stem)
    if match and match.group(1):
        return match.group(1).replace("_", " ").strip()
    if path.stem.lower() != "8-k":
        return path.stem.replace("_", " ").strip()
    return None


def _eight_k_sort_key(path: Path) -> tuple[int, str]:
    if path.stem.lower() == "8-k":
        return (0, path.name.lower())
    return (1, path.name.lower())


def discover_eight_k_paths(folder: Path) -> list[Path]:
    paths: set[Path] = set()

    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            if _is_eight_k_filename(path):
                paths.add(path.resolve())

    for subfolder_name in EIGHT_K_SUBFOLDER_NAMES:
        subfolder = folder / subfolder_name
        if not subfolder.is_dir():
            continue
        for path in subfolder.iterdir():
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                paths.add(path.resolve())

    return sorted(paths, key=_eight_k_sort_key)


def load_document(
    folder: Path,
    doc_type: DocumentType,
    *,
    quarter_label: str | None = None,
) -> LoadedDocument | None:
    path = find_document_path(folder, DOCUMENT_BASENAMES[doc_type])
    if path is None:
        return None
    text = parse_transcript(path)
    if not text.strip():
        raise ValueError(f"Document file is empty: {path.name}")
    return LoadedDocument(
        doc_type=doc_type,
        quarter_label=quarter_label,
        path=path,
        text=text,
    )


def load_eight_k_documents(folder: Path) -> list[LoadedDocument]:
    documents: list[LoadedDocument] = []
    for path in discover_eight_k_paths(folder):
        text = parse_transcript(path)
        if not text.strip():
            raise ValueError(f"Document file is empty: {path.name}")
        documents.append(
            LoadedDocument(
                doc_type=DocumentType.EIGHT_K,
                quarter_label=None,
                path=path,
                text=text,
                section_label=eight_k_section_label(path),
            )
        )
    return documents


def section_tag(
    doc_type: DocumentType,
    quarter_label: str | None = None,
    section_label: str | None = None,
) -> str:
    if doc_type == DocumentType.TEN_K and quarter_label:
        return f"10-K ({quarter_label})"
    if doc_type == DocumentType.TEN_Q and quarter_label:
        return f"10-Q ({quarter_label})"
    if doc_type == DocumentType.EIGHT_K:
        if section_label:
            return f"8-K ({section_label})"
        return "8-K"
    if doc_type == DocumentType.PRESS_RELEASE:
        return "PRESS_RELEASE"
    if doc_type == DocumentType.INVESTOR_PRESENTATION:
        return "INVESTOR_PRESENTATION"
    return doc_type.value


def build_tagged_corpus(documents: list[LoadedDocument]) -> str:
    sections: list[str] = []
    for doc in documents:
        tag = section_tag(doc.doc_type, doc.quarter_label, doc.section_label)
        sections.append(f"=== {tag} ===")
        sections.append(doc.text.strip())
        sections.append("")
    return "\n".join(sections).strip()


DEFAULT_MAX_CORPUS_CHARS = 1_200_000

SECTION_HEADER_RE = re.compile(r"^=== .+? ===$", re.MULTILINE)
TRUNCATION_MARKER = (
    "\n\n[... middle of section omitted for token budget; "
    "head and tail preserved ...]\n\n"
)


def _is_large_section_header(header: str) -> bool:
    label = header.strip("= ").strip()
    return label.startswith("10-Q") or label.startswith("10-K")


def _split_tagged_corpus(corpus: str) -> list[tuple[str, str]]:
    matches = list(SECTION_HEADER_RE.finditer(corpus))
    if not matches:
        return [("", corpus)]

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        header = match.group(0)
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(corpus)
        sections.append((header, corpus[body_start:body_end].strip()))
    return sections


def _truncate_section_body(body: str, max_body_chars: int) -> str:
    if len(body) <= max_body_chars:
        return body
    if max_body_chars <= len(TRUNCATION_MARKER) + 100:
        return body[:max_body_chars]
    head_size = int(max_body_chars * 0.4)
    tail_size = max_body_chars - head_size - len(TRUNCATION_MARKER)
    if tail_size < 50:
        return body[:max_body_chars]
    return body[:head_size] + TRUNCATION_MARKER + body[-tail_size:]


def truncate_corpus_for_llm(
    corpus: str,
    max_chars: int = DEFAULT_MAX_CORPUS_CHARS,
) -> tuple[str, list[str]]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(corpus) <= max_chars:
        return corpus, []

    sections = _split_tagged_corpus(corpus)
    small_sections: list[tuple[str, str]] = []
    large_sections: list[tuple[str, str]] = []
    for header, body in sections:
        if header and _is_large_section_header(header):
            large_sections.append((header, body))
        else:
            small_sections.append((header, body))

    def _render(section_list: list[tuple[str, str]]) -> str:
        parts: list[str] = []
        for header, body in section_list:
            if header:
                parts.extend([header, body, ""])
            elif body:
                parts.append(body)
        return "\n".join(parts).strip()

    small_text = _render(small_sections)
    overhead = max(500, len(large_sections) * 80)
    large_budget = max_chars - len(small_text) - overhead
    warnings: list[str] = []

    if not large_sections:
        truncated = corpus[:max_chars]
        warnings.append(
            f"Corpus truncated from {len(corpus):,} to {len(truncated):,} chars "
            f"(max {max_chars:,})."
        )
        return truncated, warnings

    if large_budget < 10_000:
        per_large = max(1_000, max_chars // max(len(large_sections), 1))
        truncated_large = [
            (header, _truncate_section_body(body, per_large))
            for header, body in large_sections
        ]
        result = _render(small_sections + truncated_large)
        if len(result) > max_chars:
            result = result[:max_chars]
        warnings.append(
            f"Corpus truncated from {len(corpus):,} to {len(result):,} chars "
            f"(max {max_chars:,}); kept {len(small_sections)} smaller section(s) "
            f"and head/tail of {len(large_sections)} 10-Q/10-K section(s)."
        )
        return result, warnings

    per_large = large_budget // len(large_sections)
    truncated_large = [
        (header, _truncate_section_body(body, per_large))
        for header, body in large_sections
    ]
    result = _render(small_sections + truncated_large)
    if len(result) > max_chars:
        result = result[:max_chars]
    warnings.append(
        f"Corpus truncated from {len(corpus):,} to {len(result):,} chars "
        f"(max {max_chars:,}); kept {len(small_sections)} smaller section(s) "
        f"and head/tail of {len(large_sections)} 10-Q/10-K section(s)."
    )
    return result, warnings
