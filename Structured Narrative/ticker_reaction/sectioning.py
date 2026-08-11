"""Heuristics to split prepared remarks vs Q&A."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ticker_reaction.align import AlignedUtterance, utterance_wall_clock
from ticker_reaction.load_transcript import EventAnchors, TimedTranscript

# True Q&A openers (not the call-start agenda that says Q&A will happen later).
_QA_OPERATOR_OPEN = re.compile(
    r"\b("
    r"we\s+will\s+now\s+(open|begin|take|start)|"
    r"now\s+open(ing)?\s+(the\s+)?(call|line|floor)|"
    r"(begin|beginning|start|starting)\s+(the\s+)?"
    r"(q\s*&\s*a|qa|question[- ]and[- ]answer|questions?)\b|"
    r"open(ing)?\s+(the\s+)?(call|line|floor)\s+up\s+for\s+questions?|"
    r"open(ing)?\s+(the\s+)?(call|line)\s+for\s+questions?|"
    r"(first|our\s+first)\s+question\b|"
    r"please\s+proceed\s+with\s+your\s+question|"
    r"please\s+go\s+ahead\b"
    r")",
    re.IGNORECASE,
)
# Prefatory "we will conduct a Q&A after remarks" / listen-only intros.
_QA_OPERATOR_PREFACE = re.compile(
    r"\b("
    r"after\s+the\s+presentation|"
    r"listen[- ]only|"
    r"will\s+conduct|"
    r"will\s+be\s+(taking|answering)|"
    r"later\s+in\s+the\s+call|"
    r"following\s+(the\s+)?(presentation|remarks|prepared\s+remarks)"
    r")\b",
    re.IGNORECASE,
)
_QA_ANALYST = re.compile(
    r"\b(thanks?\s+for\s+taking|i\s+have\s+(two\s+)?questions?|my\s+question)\b",
    re.IGNORECASE,
)
_MANAGEMENT_ROLES = {
    "ceo",
    "cfo",
    "coo",
    "president",
    "investor relations",
    "vp of investor relations",
    "chief executive",
    "chief financial",
}


def _is_management(speaker: str, role: str | None) -> bool:
    blob = f"{speaker or ''} {role or ''}".lower()
    if "operator" in blob:
        return False
    return any(tok in blob for tok in _MANAGEMENT_ROLES) or bool(
        re.search(r"\b(ceo|cfo)\b", blob)
    )


def _operator_opens_qa(text: str) -> bool:
    """True when Operator is opening Q&A now, not announcing it for later."""
    blob = text or ""
    if _QA_OPERATOR_PREFACE.search(blob):
        return False
    return bool(_QA_OPERATOR_OPEN.search(blob))


def detect_qa_start_sec(transcript: TimedTranscript) -> float | None:
    """
    Return start_sec of first Q&A-like turn, or None if not found.

    Prefers Operator lines that *open* Q&A now. Ignores call-start agenda lines
    like \"after the presentation, we will conduct a question-and-answer
    session\" that previously pinned the chart Q&A marker at call start.
    Falls back to analyst-style question cues, then first non-management
    speaker after several management turns.
    """
    paras = sorted(transcript.paragraphs, key=lambda p: (p.start_sec, p.index))
    for p in paras:
        sp = (p.speaker or "").strip().lower()
        if sp == "operator" and _operator_opens_qa(p.text or ""):
            return float(p.start_sec)
    for p in paras:
        if _QA_ANALYST.search(p.text or ""):
            return float(p.start_sec)
    # Fallback: first non-management speaker after at least 3 management turns
    mgmt = 0
    for p in paras:
        if _is_management(p.speaker or "", p.speaker_role):
            mgmt += 1
            continue
        sp = (p.speaker or "").strip().lower()
        if sp and sp != "operator" and mgmt >= 3:
            return float(p.start_sec)
    return None


def section_for_start(start_sec: float, qa_start_sec: float | None) -> str:
    if qa_start_sec is None:
        return "remarks"
    return "qa" if float(start_sec) >= float(qa_start_sec) else "remarks"


def section_meta(
    transcript: TimedTranscript,
    anchors: EventAnchors,
) -> dict[str, Any]:
    qa_start = detect_qa_start_sec(transcript)
    qa_utc = None
    if qa_start is not None:
        qa_utc = utterance_wall_clock(anchors.call_at, qa_start)
    return {
        "qa_start_sec": qa_start,
        "qa_start_utc": qa_utc.isoformat() if isinstance(qa_utc, datetime) else None,
        "section_heuristic": "operator_qa_open|analyst_question|non_mgmt_after_mgmt",
    }
