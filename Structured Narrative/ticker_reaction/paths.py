"""Typed Output/ path helpers for Live Ticker Reaction artifacts."""

from __future__ import annotations

from pathlib import Path

OUTPUT_KIND_REPORTS = "Reports"
OUTPUT_KIND_TABLES = "Tables"
OUTPUT_KIND_DIAGNOSTICS = "Diagnostics"

OUTPUT_KINDS = (
    OUTPUT_KIND_REPORTS,
    OUTPUT_KIND_TABLES,
    OUTPUT_KIND_DIAGNOSTICS,
)


def event_slug(ticker: str, quarter: str) -> str:
    return f"{ticker.upper()}_{quarter.upper()}"


def artifact_path(
    output_root: Path,
    kind: str,
    slug: str,
    filename: str,
    *,
    create: bool = True,
) -> Path:
    if kind not in OUTPUT_KINDS:
        raise ValueError(f"Unknown output kind {kind!r}; expected one of {OUTPUT_KINDS}")
    folder = Path(output_root) / kind / slug
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder / filename


def reports_html_path(output_root: Path, slug: str, *, create: bool = True) -> Path:
    return artifact_path(
        output_root, OUTPUT_KIND_REPORTS, slug, "ticker_reaction.html", create=create
    )


def reactions_csv_path(output_root: Path, slug: str, *, create: bool = True) -> Path:
    return artifact_path(
        output_root, OUTPUT_KIND_TABLES, slug, "reactions.csv", create=create
    )


def diagnostics_json_path(output_root: Path, slug: str, *, create: bool = True) -> Path:
    return artifact_path(
        output_root,
        OUTPUT_KIND_DIAGNOSTICS,
        slug,
        "join_diagnostics.json",
        create=create,
    )
