from __future__ import annotations

import re

from src.validation.evidence_validator import MIN_EXCERPT_LENGTH, excerpt_found_in_source, normalize_text

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "were",
        "with",
        "yo",
        "yoy",
    }
)


def _extract_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    for match in re.finditer(
        r"\$?\d[\d,]*(?:\.\d+)?%?|\b[A-Z]{2,}\b|\b[a-z]{4,}\b",
        text,
    ):
        token = match.group().strip()
        normalized = normalize_text(token)
        if normalized in _STOP_WORDS or len(normalized) < 3:
            continue
        if token not in keywords:
            keywords.append(token)
    return keywords


def _span_from_hint(source: str, hint_excerpt: str) -> str | None:
    hint_words = hint_excerpt.split()
    if len(hint_words) < 3:
        return None

    source_words = source.split()
    best: str | None = None
    best_len = 0

    for window in range(len(hint_words), 2, -1):
        for start in range(len(hint_words) - window + 1):
            phrase = " ".join(hint_words[start : start + window])
            if not excerpt_found_in_source(phrase, source):
                continue
            phrase_norm = normalize_text(phrase)
            for index in range(len(source_words)):
                for end in range(index + 3, min(len(source_words), index + window + 8) + 1):
                    candidate = " ".join(source_words[index:end])
                    candidate_norm = normalize_text(candidate)
                    if phrase_norm in candidate_norm and excerpt_found_in_source(
                        candidate, source
                    ):
                        if len(candidate_norm) > best_len:
                            best = candidate
                            best_len = len(candidate_norm)
        if best:
            return best
    return None


def _candidate_spans(source: str) -> list[str]:
    spans: list[str] = []
    for match in re.finditer(r"[^.!?]+[.!?]?", source):
        span = match.group().strip()
        if len(normalize_text(span)) >= MIN_EXCERPT_LENGTH:
            spans.append(span)
    return spans


def _best_keyword_span(source: str, keywords: list[str]) -> str | None:
    if not keywords:
        return None

    best: tuple[int, int, str] | None = None
    for span in _candidate_spans(source):
        span_norm = normalize_text(span)
        score = sum(1 for keyword in keywords if normalize_text(keyword) in span_norm)
        if score == 0:
            continue
        candidate = (score, -len(span_norm), span)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2] if best else None


def find_verbatim_quote(
    claim: str,
    source: str,
    hint_excerpt: str | None = None,
) -> str | None:
    """
    Search source for a contiguous verbatim span supporting the claim.
    Returns an original-source substring that passes excerpt_found_in_source.
    """
    hints = [hint for hint in (hint_excerpt, claim) if hint]
    for hint in hints:
        anchored = _span_from_hint(source, hint)
        if anchored:
            return anchored

    keywords = _extract_keywords(f"{claim} {hint_excerpt or ''}")
    anchored = _best_keyword_span(source, keywords)
    if anchored:
        return anchored

    return None
