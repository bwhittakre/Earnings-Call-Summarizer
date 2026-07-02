from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.filings.loader import ExcerptConfig, load_filing_packages
from src.ingest.filings.manifest import resolve_quarter_end_overrides
from src.ingest.filings.types import FilingLoadError
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH, resolve_quarter_end_date
from src.market.pipeline import build_market_context
from src.market.stock_prices import StockPriceError

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
    price_ok: list[str] = []
    price_fail: list[tuple[str, str]] = []
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
        except FilingLoadError as exc:
            filing_fail.append((quarter, str(exc)))
            print(f"FILING FAIL {quarter}: {exc}")
            continue
        except Exception as exc:
            filing_fail.append((quarter, str(exc)))
            print(f"FILING FAIL {quarter}: {exc}")
            continue

        as_of = package.as_of_date
        as_of_source = "manifest"
        if as_of is None:
            as_of = resolve_quarter_end_date(
                "AMZN",
                quarter,
                calendars_path=DEFAULT_FISCAL_CALENDARS_PATH,
            )
            as_of_source = "calendar quarter-end (no manifest)"

        try:
            overrides = resolve_quarter_end_overrides(
                package.folder,
                quarter=package.quarter,
                as_of_date=as_of,
            )
            context = build_market_context(
                ticker="AMZN",
                as_of_date=as_of,
                reported_quarter=quarter,
                audit_label=package.audit_label(),
                date_overrides=overrides,
            )
            price_summary = "; ".join(
                f"{price.quarter_label}={price.adjusted_close:.2f}"
                for price in context.prices
            )
            price_ok.append(quarter)
            print(
                f"OK {quarter} docs={len(package.documents)} "
                f"analysis={len(package.analysis_corpus_text):,} "
                f"as_of={as_of.isoformat()} ({as_of_source}) "
                f"prices=[{price_summary}]"
            )
        except (StockPriceError, Exception) as exc:
            price_fail.append((quarter, str(exc)))
            print(f"PRICE FAIL {quarter}: {exc}")

    print("=" * 60)
    print(
        f"Filing validation: {len(filing_ok)}/{len(quarters)} OK, "
        f"{len(filing_fail)} failed"
    )
    print(
        f"Price fetch:       {len(price_ok)}/{len(quarters)} OK, "
        f"{len(price_fail)} failed"
    )
    print(f"Missing manifest:  {len(no_manifest)} quarters")
    if filing_fail:
        print("Filing failures:")
        for quarter, message in filing_fail:
            print(f"  {quarter}: {message}")
    if price_fail:
        print("Price failures:")
        for quarter, message in price_fail:
            print(f"  {quarter}: {message}")
    return 1 if filing_fail or price_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
