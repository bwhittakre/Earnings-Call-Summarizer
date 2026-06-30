from __future__ import annotations

from datetime import date

from src.ingest.call_date import resolve_call_date_value
from src.ingest.loader import normalize_quarter_label
from src.ingest.reported_quarter import (
    ReportedQuarterError,
    extract_reported_quarter,
    resolve_reported_quarter,
)
from src.pipeline.point_in_time import PointInTimeConfig, PointInTimeError


def resolve_strict_anchoring(
    *,
    transcript_text: str,
    filename_quarter: str,
    point_in_time: PointInTimeConfig,
    reported_quarter_override: str | None = None,
    require_call_date: bool = False,
) -> tuple[date | None, str]:
    """Resolve call date and reported quarter with optional strict validation."""
    if point_in_time.active and reported_quarter_override:
        raise PointInTimeError(
            "--reported-quarter is not allowed in point-in-time mode. "
            "The reported quarter must be parsed from the transcript and match the filename."
        )

    if point_in_time.active or require_call_date:
        try:
            call_date = resolve_call_date_value(transcript_text)
        except ReportedQuarterError as exc:
            if point_in_time.active:
                raise PointInTimeError(str(exc)) from exc
            raise
    else:
        call_date = None

    if point_in_time.active:
        transcript_quarter = extract_reported_quarter(transcript_text)
        if not transcript_quarter:
            raise PointInTimeError(
                "Could not extract reported quarter from transcript opening. "
                "Point-in-time mode requires an explicit quarter in IR remarks."
            )
        normalized_transcript = normalize_quarter_label(transcript_quarter)
        normalized_filename = normalize_quarter_label(filename_quarter)
        if normalized_transcript != normalized_filename:
            raise PointInTimeError(
                f"Filename quarter {normalized_filename!r} does not match "
                f"transcript quarter {normalized_transcript!r}. "
                "Rename the file or fix the transcript opening."
            )
        return call_date, normalized_transcript

    reported_quarter = resolve_reported_quarter(
        transcript_text,
        cli_override=reported_quarter_override or filename_quarter,
    )
    return call_date, reported_quarter
