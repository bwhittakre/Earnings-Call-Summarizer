"""Deterministic transcript normalization, fingerprinting, and stabilization."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import TranscriptDocument


def normalize_transcript(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def transcript_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_transcript(text).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StabilizationDecision:
    ready: bool
    fingerprint: str
    reason: str
    first_observed_at: datetime


class TranscriptStabilizer:
    def __init__(self, *, stable_for: timedelta, minimum_chars: int = 1_000):
        if stable_for.total_seconds() < 0:
            raise ValueError("stable_for cannot be negative")
        if minimum_chars < 1:
            raise ValueError("minimum_chars must be positive")
        self.stable_for = stable_for
        self.minimum_chars = minimum_chars

    def assess(
        self,
        document: TranscriptDocument,
        *,
        previous_fingerprint: str | None,
        first_observed_at: datetime | None,
        now: datetime | None = None,
    ) -> StabilizationDecision:
        current = now or datetime.now(timezone.utc)
        content = normalize_transcript(document.content)
        fingerprint = transcript_fingerprint(content)
        first = first_observed_at or current
        if len(content) < self.minimum_chars:
            return StabilizationDecision(False, fingerprint, "transcript below minimum size", current)
        if previous_fingerprint != fingerprint:
            return StabilizationDecision(False, fingerprint, "new transcript version observed", current)
        if current - first < self.stable_for:
            return StabilizationDecision(False, fingerprint, "stabilization window not elapsed", first)
        return StabilizationDecision(True, fingerprint, "transcript stable", first)
