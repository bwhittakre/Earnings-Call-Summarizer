from __future__ import annotations

from pathlib import Path

from src.paths import PROJECT_ROOT

DEFAULT_SECTORS_DIR = PROJECT_ROOT / "config" / "sectors"


class CompanyListError(Exception):
    pass


def _normalize_entry(line: str) -> str | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if "#" in text:
        text = text.split("#", 1)[0].strip()
    return text or None


def parse_company_list_text(text: str) -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        entry = _normalize_entry(line)
        if not entry:
            continue
        key = entry.upper()
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    if not entries:
        raise CompanyListError("Company list is empty.")
    return entries


def load_companies_file(path: Path) -> list[str]:
    if not path.is_file():
        raise CompanyListError(f"Companies file not found: {path}")
    return parse_company_list_text(path.read_text(encoding="utf-8"))


def resolve_sector_file(sector: str, *, sectors_dir: Path = DEFAULT_SECTORS_DIR) -> Path:
    key = sector.strip()
    if not key:
        raise CompanyListError("Sector name cannot be empty.")
    if not sectors_dir.is_dir():
        raise CompanyListError(f"Sectors directory not found: {sectors_dir}")

    normalized = key.lower().replace(" ", "_").replace("-", "_")
    candidate = sectors_dir / f"{normalized}.txt"
    if candidate.is_file():
        return candidate

    available = list_available_sectors(sectors_dir=sectors_dir)
    if available:
        raise CompanyListError(
            f"Unknown sector {sector!r}. Available: {', '.join(available)}"
        )
    raise CompanyListError(f"Unknown sector {sector!r} and no sector lists found in {sectors_dir}.")


def load_sector_companies(sector: str, *, sectors_dir: Path = DEFAULT_SECTORS_DIR) -> list[str]:
    path = resolve_sector_file(sector, sectors_dir=sectors_dir)
    return load_companies_file(path)


def list_available_sectors(*, sectors_dir: Path = DEFAULT_SECTORS_DIR) -> list[str]:
    if not sectors_dir.is_dir():
        return []
    return sorted(path.stem for path in sectors_dir.glob("*.txt"))


def format_companies_csv(entries: list[str]) -> str:
    return ",".join(entries)


def resolve_companies_argument(
    *,
    companies: str | None = None,
    companies_file: str | None = None,
    sector: str | None = None,
    sectors_dir: Path = DEFAULT_SECTORS_DIR,
) -> str:
    sources = [companies, companies_file, sector]
    provided = sum(1 for value in sources if value)
    if provided != 1:
        raise CompanyListError(
            "Provide exactly one of --companies, --companies-file, or --sector."
        )

    if companies:
        return companies.strip()

    if companies_file:
        entries = load_companies_file(Path(companies_file))
        return format_companies_csv(entries)

    assert sector is not None
    entries = load_sector_companies(sector, sectors_dir=sectors_dir)
    return format_companies_csv(entries)
