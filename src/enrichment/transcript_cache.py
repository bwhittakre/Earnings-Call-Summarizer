from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.paths import DEFAULT_TRANSCRIPTS_ROOT


def ticker_transcripts_folder(ticker: str, root: Path = DEFAULT_TRANSCRIPTS_ROOT) -> Path:
    return root / ticker.strip().lower()


def quarter_transcript_path(
    ticker: str,
    quarter_label: str,
    root: Path = DEFAULT_TRANSCRIPTS_ROOT,
) -> Path:
    return ticker_transcripts_folder(ticker, root) / f"{quarter_label}.txt"


def quarter_transcript_dir(
    ticker: str,
    quarter_label: str,
    root: Path = DEFAULT_TRANSCRIPTS_ROOT,
) -> Path:
    return ticker_transcripts_folder(ticker, root) / quarter_label


def manifest_path(
    ticker: str,
    quarter_label: str,
    root: Path = DEFAULT_TRANSCRIPTS_ROOT,
) -> Path:
    return quarter_transcript_dir(ticker, quarter_label, root) / "manifest.json"


def read_cached_transcript(
    ticker: str,
    quarter_label: str,
    root: Path = DEFAULT_TRANSCRIPTS_ROOT,
) -> tuple[str, dict] | None:
    flat_path = quarter_transcript_path(ticker, quarter_label, root)
    if flat_path.is_file():
        text = flat_path.read_text(encoding="utf-8", errors="replace")
        manifest_file = manifest_path(ticker, quarter_label, root)
        manifest = (
            json.loads(manifest_file.read_text(encoding="utf-8"))
            if manifest_file.is_file()
            else {"source": "local_cache", "path": str(flat_path)}
        )
        return text, manifest

    nested_path = quarter_transcript_dir(ticker, quarter_label, root) / "transcript.txt"
    manifest_file = manifest_path(ticker, quarter_label, root)
    if nested_path.is_file():
        text = nested_path.read_text(encoding="utf-8", errors="replace")
        manifest = (
            json.loads(manifest_file.read_text(encoding="utf-8"))
            if manifest_file.is_file()
            else {"source": "local_cache", "path": str(nested_path)}
        )
        return text, manifest
    return None


def write_transcript_cache(
    ticker: str,
    quarter_label: str,
    text: str,
    *,
    source: str,
    url: str | None = None,
    root: Path = DEFAULT_TRANSCRIPTS_ROOT,
) -> Path:
    folder = quarter_transcript_dir(ticker, quarter_label, root)
    folder.mkdir(parents=True, exist_ok=True)
    transcript_path = folder / "transcript.txt"
    transcript_path.write_text(text, encoding="utf-8")

    manifest = {
        "source": source,
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "transcript_path": str(transcript_path),
    }
    manifest_file = manifest_path(ticker, quarter_label, root)
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return transcript_path
