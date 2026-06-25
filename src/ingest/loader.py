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


def normalize_quarter_label(label: str) -> str:
    parsed = parse_quarter_from_filename(Path(label.strip()))
    if not parsed:
        raise TranscriptLoadError(
            "Invalid quarter label. Use FY2025-Q2 or 2025-Q2 format."
        )
    return parsed


def transcript_audit_label(item: TranscriptFile) -> str:
    return f"{item.path.stem}_quarter"


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


def resolve_transcript_files(
    transcript_path: Path,
    quarter: str | None = None,
) -> list[TranscriptFile]:
    if not transcript_path.exists():
        raise TranscriptLoadError(f"Transcript path not found: {transcript_path}")

    if transcript_path.is_file():
        if transcript_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise TranscriptLoadError(
                f"Unsupported transcript file type: {transcript_path.suffix}. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )
        file_quarter = parse_quarter_from_filename(transcript_path)
        if not file_quarter:
            raise TranscriptLoadError(
                "Transcript file must include a quarter label (FY2025-Q2 or 2025-Q2) "
                f"in the filename: {transcript_path.name}"
            )
        if quarter and normalize_quarter_label(quarter) != file_quarter:
            raise TranscriptLoadError(
                f"--quarter {quarter} does not match file quarter {file_quarter} "
                f"for {transcript_path.name}"
            )
        return [
            TranscriptFile(
                path=transcript_path,
                quarter=file_quarter,
                quarter_from_filename=True,
            )
        ]

    if not transcript_path.is_dir():
        raise TranscriptLoadError(f"Transcript path is not a file or directory: {transcript_path}")

    assigned = assign_quarters(discover_transcript_files(transcript_path))
    if quarter:
        target = normalize_quarter_label(quarter)
        matched = [item for item in assigned if item.quarter == target]
        if not matched:
            available = ", ".join(item.quarter for item in assigned) or "(none)"
            raise TranscriptLoadError(
                f"Quarter {target} not found in {transcript_path}. "
                f"Available: {available}"
            )
        return matched
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


def load_transcripts(
    transcript_path: Path,
    expected_quarters: int = 1,
    quarter: str | None = None,
) -> LoadedTranscripts:
    assigned = resolve_transcript_files(transcript_path, quarter=quarter)
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
        transcripts=transcripts,
        files=assigned,
    )


def dry_run_report(
    transcript_path: Path,
    expected_quarters: int = 1,
    quarter: str | None = None,
) -> str:
    lines = [
        "Company: (auto-detect from transcript)",
        f"Path: {transcript_path}",
        f"Expected quarters: {expected_quarters}",
    ]
    if quarter:
        lines.append(f"Quarter filter: {normalize_quarter_label(quarter)}")

    try:
        assigned = resolve_transcript_files(transcript_path, quarter=quarter)
    except TranscriptLoadError as exc:
        lines.append(f"Validation: FAILED - {exc}")
        return "\n".join(lines)

    lines.append(f"Selected files: {len(assigned)}")
    for item in assigned:
        source = "filename" if item.quarter_from_filename else "fallback"
        lines.append(f"  - {item.path.name} -> {item.quarter} ({source})")
    try:
        validate_transcript_count(assigned, expected_quarters)
        lines.append("Validation: OK")
    except TranscriptLoadError as exc:
        lines.append(f"Validation: FAILED - {exc}")
    return "\n".join(lines)
