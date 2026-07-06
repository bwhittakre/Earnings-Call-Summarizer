from __future__ import annotations

import logging
from pathlib import Path

from src.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

GITIGNORE_PATH = PROJECT_ROOT / ".gitignore"
AUTO_START = "# AUTO: fetched filing roots"
AUTO_END = "# END AUTO"
DATA_FILINGS_PATTERN = "data/filings/"


def _normalize_gitignore_pattern(relative: Path) -> str | None:
    text = relative.as_posix().strip()
    if not text or text == ".":
        return None
    if text.endswith("/"):
        return text
    return f"{text}/"


def filing_root_gitignore_patterns(
    filings_root: Path,
    tickers: list[str],
    *,
    project_root: Path = PROJECT_ROOT,
) -> list[str]:
    """Return .gitignore patterns for fetched filing trees under the repo."""
    try:
        root = filings_root.expanduser().resolve()
        repo = project_root.resolve()
        root.relative_to(repo)
    except ValueError:
        return []

    patterns: list[str] = []
    resolved_filings_root = filings_root.expanduser().resolve()
    try:
        resolved_filings_root.relative_to(project_root.resolve())
    except ValueError:
        return []

    filings_relative = resolved_filings_root.relative_to(project_root.resolve())
    if filings_relative.parts == ():
        for ticker in tickers:
            pattern = _normalize_gitignore_pattern(Path(ticker.strip().upper()))
            if pattern:
                patterns.append(pattern)
    elif filings_relative.as_posix().startswith("data/filings"):
        patterns.append(DATA_FILINGS_PATTERN)
    else:
        for ticker in tickers:
            pattern = _normalize_gitignore_pattern(
                filings_relative / ticker.strip().upper()
            )
            if pattern:
                patterns.append(pattern)

    deduped: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        if pattern not in seen:
            seen.add(pattern)
            deduped.append(pattern)
    return deduped


def _parse_auto_section(lines: list[str]) -> tuple[list[str], int | None, int | None]:
    start = end = None
    for index, line in enumerate(lines):
        if line.strip() == AUTO_START:
            start = index
        elif line.strip() == AUTO_END and start is not None:
            end = index
            break
    if start is None or end is None or end <= start:
        return [], None, None
    return lines[start + 1 : end], start, end


def sync_filings_gitignore(
    filings_root: Path,
    tickers: list[str],
    *,
    project_root: Path = PROJECT_ROOT,
    gitignore_path: Path = GITIGNORE_PATH,
) -> bool:
    """Idempotently add gitignore patterns for fetched company filing trees."""
    patterns = filing_root_gitignore_patterns(
        filings_root,
        tickers,
        project_root=project_root,
    )
    if not patterns:
        return False

    if not gitignore_path.is_file():
        return False

    lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    existing_auto, start, end = _parse_auto_section(lines)
    merged = sorted(set(existing_auto + patterns))
    if merged == existing_auto:
        return False

    new_section = [AUTO_START, *merged, AUTO_END]
    if start is None or end is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(new_section)
    else:
        lines = [*lines[:start], *new_section, *lines[end + 1 :]]

    gitignore_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Updated .gitignore for fetched filings: %s", ", ".join(patterns))
    return True
