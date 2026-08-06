"""Heuristics to split prepared remarks vs Q&A."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ticker_reaction.align import AlignedUtterance, utterance_wall_clock
from ticker_reaction.load_transcript import EventAnchors, TimedTranscript

_QA_OPERATOR = re.compile(
    r"\b(question|questions|q\s*&\s*a|qa)\b",
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


def detect_qa_start_sec(transcript: TimedTranscript) -> float | None:
    """
    Return start_sec of first Q&A-like turn, or None if not found.
    Prefers Operator opening Q&A; else analyst-style question cues.
    """
    paras = sorted(transcript.paragraphs, key=lambda p: (p.start_sec, p.index))
    for p in paras:
        sp = (p.speaker or "").strip().lower()
        text = p.text or ""
        if sp == "operator" and _QA_OPERATOR.search(text):
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
        "section_heuristic": "operator_qa_cue|analyst_question|non_mgmt_after_mgmt",
    }
