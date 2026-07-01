from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.ingest.dates import parse_as_of_date_format, resolve_as_of_date_text
from src.ingest.filings.fiscal import normalize_quarter_label
from src.ingest.filings.types import FilingLoadError


@dataclass
class ManifestData:
    ticker: str | None
    company_name: str | None
    quarter: str | None
    fiscal_year: str | None
    as_of_date: str | None


def load_manifest(folder: Path) -> ManifestData | None:
    path = folder / "manifest.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FilingLoadError(f"Invalid manifest.json in {folder}: {exc}") from exc
    if not isinstance(raw, dict):
        raise FilingLoadError(f"manifest.json must be a JSON object: {folder}")
    return ManifestData(
        ticker=_optional_str(raw.get("ticker")),
        company_name=_optional_str(raw.get("company_name")),
        quarter=_optional_str(raw.get("quarter")),
        fiscal_year=_optional_str(raw.get("fiscal_year")),
        as_of_date=_optional_str(raw.get("as_of_date")),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validate_manifest(
    manifest: ManifestData | None,
    *,
    folder: Path,
    ticker: str,
    quarter: str,
    require_as_of_date: bool = False,
) -> tuple[str | None, str | None, str | None, list[str]]:
    warnings: list[str] = []
    company_name = manifest.company_name if manifest else None
    as_of_date_text = manifest.as_of_date if manifest else None
    fiscal_year = manifest.fiscal_year if manifest else None

    if manifest is None:
        warnings.append(f"No manifest.json in {folder.name}; using folder metadata only.")
    else:
        if manifest.ticker and manifest.ticker.strip().upper() != ticker.upper():
            raise FilingLoadError(
                f"manifest ticker {manifest.ticker!r} does not match folder ticker {ticker!r}"
            )
        if manifest.quarter:
            if normalize_quarter_label(manifest.quarter) != quarter:
                raise FilingLoadError(
                    f"manifest quarter {manifest.quarter!r} does not match "
                    f"folder quarter {quarter!r}"
                )
        if manifest.as_of_date and parse_as_of_date_format(manifest.as_of_date) is None:
            raise FilingLoadError(
                f"manifest as_of_date must be (mm,dd,yyyy): {manifest.as_of_date!r}"
            )

    if require_as_of_date and not resolve_as_of_date_text(as_of_date_text):
        raise FilingLoadError(
            f"as_of_date required in manifest.json for point-in-time mode: {folder}"
        )

    return company_name, as_of_date_text, fiscal_year, warnings


def resolve_quarter_end_overrides(
    folder: Path,
    *,
    quarter: str,
    as_of_date: date | None,
) -> dict[str, date]:
    overrides: dict[str, date] = {}
    if as_of_date is not None:
        overrides[normalize_quarter_label(quarter)] = as_of_date

    parent = folder.parent
    if not parent.is_dir():
        return overrides

    for child in sorted(parent.iterdir()):
        if not child.is_dir():
            continue
        manifest = load_manifest(child)
        if manifest is None or not manifest.quarter or not manifest.as_of_date:
            continue
        parsed = parse_as_of_date_format(manifest.as_of_date)
        if parsed is None:
            continue
        overrides[normalize_quarter_label(manifest.quarter)] = parsed

    return overrides
