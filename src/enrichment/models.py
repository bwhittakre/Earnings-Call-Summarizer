from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from src.schemas.models import EvidenceClaim


class EnrichmentResult(BaseModel):
    quarter: str
    positives: list[EvidenceClaim] = Field(default_factory=list)
    negatives: list[EvidenceClaim] = Field(default_factory=list)
    key_quotes: list[EvidenceClaim] = Field(default_factory=list)
    availability: Literal["found", "missing"] = "missing"
    notes: str = ""


@dataclass
class TranscriptSource:
    quarter: str
    text: str
    source: str
    url: str | None = None
    fetched_at: str | None = None
