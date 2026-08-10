"""Deterministic transcript normalization, fingerprinting, and stabilization.

Readiness is driven by **content stagnation**, not Quartr's sticky
live/ongoing → final status flip (which can lag several minutes after
speaking ends).

Env knobs (via MonitorConfig):
- EARNINGS_MONITOR_STABILIZATION_SECONDS — no-change window before ready
  (default 45). Content hash must stay identical for this long.
- EARNINGS_MONITOR_MIN_CHARS — minimum normalized size before ready.
- EARNINGS_MONITOR_REQUIRE_LIVE_GROWTH — when true (default), LIVE bundles
  must grow at least once before stagnation can fire (avoids scoring a
  pre-call empty/stub dump). FINAL bundles skip this guard.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import TranscriptDocument, TranscriptStatus

# Fingerprint metadata prefixes used only while a LIVE transcript is still
# waiting for growth. Ready decisions always return a bare content hash so
# job idempotency keys stay stable.
_INIT_PREFIX = "init:"
_GREW_PREFIX = "grew:"
_LEGACY_LIVE_PREFIX = "live:"


def normalize_transcript(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def transcript_fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_transcript(text).encode("utf-8")).hexdigest()


def _split_fingerprint(value: str | None) -> tuple[str | None, str]:
    """Return (content_hash, meta) where meta is init|grew|legacy|''."""
    if value is None:
        return None, ""
    if value.startswith(_INIT_PREFIX):
        return value[len(_INIT_PREFIX) :], "init"
    if value.startswith(_GREW_PREFIX):
        return value[len(_GREW_PREFIX) :], "grew"
    if value.startswith(_LEGACY_LIVE_PREFIX):
        return value[len(_LEGACY_LIVE_PREFIX) :], "legacy"
    return value, ""


@dataclass(frozen=True)
class StabilizationDecision:
    ready: bool
    fingerprint: str
    reason: str
    first_observed_at: datetime


class TranscriptStabilizer:
    def __init__(
        self,
        *,
        stable_for: timedelta,
        minimum_chars: int = 1_000,
        require_live_growth: bool = True,
    ):
        if stable_for.total_seconds() < 0:
            raise ValueError("stable_for cannot be negative")
        if minimum_chars < 1:
            raise ValueError("minimum_chars must be positive")
        self.stable_for = stable_for
        self.minimum_chars = minimum_chars
        self.require_live_growth = require_live_growth

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
        content_fp = transcript_fingerprint(content)
        previous_content_fp, previous_meta = _split_fingerprint(previous_fingerprint)
        is_live = document.status == TranscriptStatus.LIVE

        if len(content) < self.minimum_chars:
            # Keep growth meta if we already saw growth on a shorter draft.
            stored = content_fp
            if is_live and self.require_live_growth:
                if previous_meta == "grew" or (
                    previous_content_fp is not None and previous_content_fp != content_fp
                ):
                    stored = f"{_GREW_PREFIX}{content_fp}"
                else:
                    stored = f"{_INIT_PREFIX}{content_fp}"
            return StabilizationDecision(
                False, stored, "transcript below minimum size", current
            )

        if previous_content_fp != content_fp:
            # First poll or content changed — never ready on this observation.
            if is_live and self.require_live_growth:
                if previous_fingerprint is None:
                    stored = f"{_INIT_PREFIX}{content_fp}"
                else:
                    stored = f"{_GREW_PREFIX}{content_fp}"
            else:
                stored = content_fp
            return StabilizationDecision(
                False, stored, "new transcript version observed", current
            )

        # Same content as last observation.
        first = first_observed_at or current
        if is_live and self.require_live_growth and previous_meta in {"init", "legacy"}:
            # Still on the first LIVE sighting (or legacy live: marker). Wait for
            # at least one content growth before the stagnation clock can fire.
            # Bare hashes are allowed through: they mean a prior ready decision
            # or a non-growth observation path already accepted this content.
            stored = (
                previous_fingerprint
                if previous_fingerprint and previous_fingerprint.startswith(_INIT_PREFIX)
                else f"{_INIT_PREFIX}{content_fp}"
            )
            return StabilizationDecision(
                False,
                stored,
                "awaiting live transcript growth before stagnation",
                first,
            )

        if current - first < self.stable_for:
            stored = content_fp
            if is_live and self.require_live_growth and previous_meta == "grew":
                stored = f"{_GREW_PREFIX}{content_fp}"
            return StabilizationDecision(
                False, stored, "stabilization window not elapsed", first
            )

        # Ready: always bare content hash (status LIVE or FINAL does not gate).
        reason = (
            "live transcript stagnated"
            if is_live
            else "transcript stable"
        )
        return StabilizationDecision(True, content_fp, reason, first)
