from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from src.schemas.models import QuarterSummary


@dataclass
class BatchQuarterResult:
    quarter_label: str
    status: Literal["success", "failed", "skipped"]
    summary: QuarterSummary | None = None
    error_message: str | None = None
    knowledge_cutoff: date | None = None
    manifest_path: Path | None = None
    attempts: int = 1
    last_error: str | None = None
    backfilled_from_analysis: list[str] = field(default_factory=list)
    enrichment: object | None = None
    fetch_summary: str = ""
    evidence_audit_path: Path | None = None
    filing_evidence: object | None = None


@dataclass
class DeferredQuarter:
    quarter_label: str
    knowledge_cutoff: date | None
    manifest_path: Path | None
    last_error: str
    sort_key: tuple[int, int]
