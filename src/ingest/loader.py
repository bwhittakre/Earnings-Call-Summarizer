from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.ingest.parsers import SUPPORTED_EXTENSIONS, parse_transcript

QUARTER_PATTERN = re.compile(r"(?:FY)?(20\d{2})-Q([1-4])", re.IGNORECASE)


@dataclass
class TranscriptFile:
    path: Path
    quarter: str
    quarter_from_filename: bool


@dataclass
class LoadedTranscripts:
    company_name: str
    transcripts: dict[str, str]
    files: list[TranscriptFile]


class TranscriptLoadError(Exception):
    pass


def parse_quarter_from_filename(path: Path) -> str | None:
    match = QUARTER_PATTERN.search(path.stem)
    if not match:
        return None
    year = match.group(1)
    quarter_num = match.group(2).upper()
    matched_text = match.group(0)
    if matched_text.upper().startswith("FY"):
        return f"FY{year}-Q{quarter_num}"
    return f"{year}-Q{quarter_num}"


def discover_transcript_files(folder: Path) -> list[Path]:
    if not folder.exists():
        raise TranscriptLoadError(f"Transcript folder not found: {folder}")
    if not folder.is_dir():
        raise TranscriptLoadError(f"Transcript path is not a directory: {folder}")

    files = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return files


def assign_quarters(files: list[Path]) -> list[TranscriptFile]:
    assigned: list[TranscriptFile] = []
    used_quarters: set[str] = set()

    for path in files:
        quarter = parse_quarter_from_filename(path)
        if quarter:
            if quarter in used_quarters:
                raise TranscriptLoadError(
                    f"Duplicate quarter '{quarter}' detected in folder: {path.parent}"
                )
            used_quarters.add(quarter)
            assigned.append(
                TranscriptFile(path=path, quarter=quarter, quarter_from_filename=True)
            )

    unnamed = [path for path in files if parse_quarter_from_filename(path) is None]
    if unnamed:
        if assigned:
            raise TranscriptLoadError(
                "Some files lack a quarter label (FY2025-Q2 or 2025-Q2) in the filename. "
                f"Rename or remove: {', '.join(p.name for p in unnamed)}"
            )
        for index, path in enumerate(sorted(unnamed, key=lambda p: p.name)):
            quarter = f"UNKNOWN-Q{index + 1}"
            assigned.append(
                TranscriptFile(path=path, quarter=quarter, quarter_from_filename=False)
            )

    assigned.sort(key=lambda item: item.quarter)
    return assigned


def validate_transcript_count(
    files: list[TranscriptFile], expected: int
) -> None:
    if len(files) != expected:
        found = [item.quarter for item in files]
        raise TranscriptLoadError(
            f"Expected {expected} transcript files, found {len(files)}. "
            f"Quarters found: {', '.join(found) if found else '(none)'}"
        )

    unnamed = [item for item in files if not item.quarter_from_filename]
    if unnamed:
        raise TranscriptLoadError(
            "All transcript files must include a quarter label (FY2025-Q2 or 2025-Q2) "
            "in the filename. "
            f"Missing on: {', '.join(item.path.name for item in unnamed)}"
        )


def load_company_transcripts(
    company_name: str,
    folder: Path,
    expected_quarters: int = 8,
) -> LoadedTranscripts:
    files = discover_transcript_files(folder)
    assigned = assign_quarters(files)
    validate_transcript_count(assigned, expected_quarters)

    transcripts: dict[str, str] = {}
    for item in assigned:
        try:
            transcripts[item.quarter] = parse_transcript(item.path)
        except Exception as exc:
            raise TranscriptLoadError(
                f"Failed to parse {item.path.name}: {exc}"
            ) from exc
        if not transcripts[item.quarter].strip():
            raise TranscriptLoadError(f"Transcript file is empty: {item.path.name}")

    return LoadedTranscripts(
        company_name=company_name,
        transcripts=transcripts,
        files=assigned,
    )


def dry_run_report(company_name: str, folder: Path, expected_quarters: int = 8) -> str:
    files = discover_transcript_files(folder)
    assigned = assign_quarters(files)
    lines = [
        f"Company: {company_name}",
        f"Folder: {folder}",
        f"Expected quarters: {expected_quarters}",
        f"Found files: {len(files)}",
    ]
    for item in assigned:
        source = "filename" if item.quarter_from_filename else "fallback"
        lines.append(f"  - {item.path.name} -> {item.quarter} ({source})")
    try:
        validate_transcript_count(assigned, expected_quarters)
        lines.append("Validation: OK")
    except TranscriptLoadError as exc:
        lines.append(f"Validation: FAILED - {exc}")
    return "\n".join(lines)
