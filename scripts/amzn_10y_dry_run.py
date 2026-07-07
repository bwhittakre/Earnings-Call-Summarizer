from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.filings.loader import ExcerptConfig, load_filing_packages
from src.ingest.filings.types import FilingLoadError

ROOT = Path("AMZN/Amazon")
FILINGS_ROOT = Path(".")


def discover_quarters() -> list[str]:
    quarters: list[str] = []
    for fiscal_year in sorted(ROOT.iterdir()):
        if not fiscal_year.is_dir():
            continue
        for quarter_dir in sorted(fiscal_year.iterdir()):
            if quarter_dir.is_dir() and "-Q" in quarter_dir.name:
                quarters.append(quarter_dir.name)
    return quarters


def main() -> int:
    quarters = discover_quarters()
    config = ExcerptConfig(mode="smart")
    filing_ok: list[str] = []
    filing_fail: list[tuple[str, str]] = []
    no_manifest: list[str] = []

    print(f"AMZN 10-year dry run: {len(quarters)} quarters")
    print("=" * 60)

    for quarter in quarters:
        try:
            packages = load_filing_packages(
                FILINGS_ROOT,
                companies="AMZN",
                quarter=quarter,
                excerpt_config=config,
            )
            package = packages[0]
            filing_ok.append(quarter)
            if not (package.folder / "manifest.json").is_file():
                no_manifest.append(quarter)
            print(
                f"OK {quarter} docs={len(package.documents)} "
                f"analysis={len(package.analysis_corpus_text):,} "
                f"as_of={package.as_of_date.isoformat() if package.as_of_date else 'unknown'}"
            )
        except FilingLoadError as exc:
            filing_fail.append((quarter, str(exc)))
            print(f"FILING FAIL {quarter}: {exc}")
        except Exception as exc:
            filing_fail.append((quarter, str(exc)))
            print(f"FILING FAIL {quarter}: {exc}")

    print("=" * 60)
    print(
        f"Filing validation: {len(filing_ok)}/{len(quarters)} OK, "
        f"{len(filing_fail)} failed"
    )
    print(f"Missing manifest:  {len(no_manifest)} quarters")
    if filing_fail:
        print("Filing failures:")
        for quarter, message in filing_fail:
            print(f"  {quarter}: {message}")
    return 1 if filing_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
