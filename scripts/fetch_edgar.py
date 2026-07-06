from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.edgar.models import EdgarFetchError
from src.ingest.edgar.resolver import fetch_quarter_package, fetch_quarter_range
from src.ingest.filings import dry_run_report, load_filing_packages
from src.ingest.filings.loader import ExcerptConfig


def _format_plan(result) -> str:
    plan = result.plan
    lines = [
        f"{plan.quarter} -> {plan.folder}",
        f"  period_end={plan.period_end.isoformat()} as_of={plan.as_of_date_text}",
    ]
    for doc in plan.documents:
        lines.append(
            f"  {doc.filename}: {doc.filing.form} {doc.filing.accession_number} "
            f"filed={doc.filing.filing_date.isoformat()} "
            f"url={doc.filing.source_url}"
        )
    if result.skipped:
        lines.append("  status=skipped (existing package complete)")
    elif result.documents:
        lines.append(f"  status=fetched ({len(result.documents)} documents)")
    else:
        lines.append("  status=planned (dry-run)")
    return "\n".join(lines)


def _validate_package(ticker: str, quarter: str, filings_root: Path) -> int:
    packages = load_filing_packages(
        filings_root,
        companies=ticker,
        quarter=quarter,
        excerpt_config=ExcerptConfig(mode="smart"),
    )
    report = dry_run_report(
        filings_root,
        companies=ticker,
        quarter=quarter,
        excerpt_config=ExcerptConfig(mode="smart"),
    )
    print(report)
    print(f"Validated {len(packages)} package(s) for {ticker} {quarter}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch SEC EDGAR filings into the local quarter folder layout."
    )
    parser.add_argument("--ticker", required=True, help="Ticker symbol, e.g. AMZN")
    parser.add_argument("--quarter", help="Single quarter label, e.g. FY2019-Q3")
    parser.add_argument("--from", dest="from_quarter", help="Range start quarter")
    parser.add_argument("--to", dest="to_quarter", help="Range end quarter")
    parser.add_argument(
        "--filings-root",
        default=".",
        help="Root folder containing ticker filing trees (default: .)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve filings and print plan without downloading",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download even when the quarter folder is complete",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run filing loader dry-run validation after fetch",
    )
    args = parser.parse_args()

    filings_root = Path(args.filings_root)
    if not args.quarter and not (args.from_quarter and args.to_quarter):
        parser.error("Provide --quarter or both --from and --to.")
    if args.quarter and (args.from_quarter or args.to_quarter):
        parser.error("Use either --quarter or a --from/--to range, not both.")

    try:
        if args.quarter:
            result = fetch_quarter_package(
                ticker=args.ticker,
                quarter=args.quarter,
                filings_root=filings_root,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
            )
            print(_format_plan(result))
            if args.validate and not args.dry_run:
                return _validate_package(args.ticker, args.quarter, filings_root)
            return 0

        results = fetch_quarter_range(
            ticker=args.ticker,
            from_quarter=args.from_quarter,
            to_quarter=args.to_quarter,
            filings_root=filings_root,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
        for result in results:
            print(_format_plan(result))
            print()
        if args.validate and not args.dry_run:
            for result in results:
                code = _validate_package(
                    args.ticker,
                    result.plan.quarter,
                    filings_root,
                )
                if code != 0:
                    return code
        return 0
    except EdgarFetchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
