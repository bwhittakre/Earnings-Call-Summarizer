from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.ingest.dates import format_as_of_date


class PointInTimeError(Exception):
    """Raised when point-in-time strict validation fails."""


@dataclass(frozen=True)
class PointInTimeConfig:
    strict: bool = False

    @classmethod
    def disabled(cls) -> PointInTimeConfig:
        return cls()

    @classmethod
    def document_only(cls) -> PointInTimeConfig:
        return cls(strict=True)

    @classmethod
    def transcript_only(cls) -> PointInTimeConfig:
        return cls.document_only()

    @property
    def active(self) -> bool:
        return self.strict


def format_point_in_time_dry_run_lines(
    *,
    as_of_date: date,
    reported_quarter: str,
) -> list[str]:
    return [
        "Point-in-time mode: point-in-time (documents-only)",
        "Rescue judge: disabled",
        f"As-of date: {format_as_of_date(as_of_date)}",
        f"Reported quarter: {reported_quarter}",
        "Point-in-time validation: OK",
    ]
