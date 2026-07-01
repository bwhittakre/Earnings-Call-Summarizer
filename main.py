from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.export.csv_writer import write_output
from src.ingest.filings import FilingLoadError, dry_run_report, load_filing_packages
from src.ingest.filings.fiscal import parse_quarters_list
from src.ingest.filings.corpus import DEFAULT_MAX_CORPUS_CHARS
from src.ingest.filings.excerpt_puller import DEFAULT_MAX_ANALYSIS_CHARS
from src.ingest.filings.loader import ExcerptConfig, normalize_excerpt_mode
from src.llm.anthropic_client import AnthropicClient
from src.market.fiscal_calendar import (
    DEFAULT_FISCAL_CALENDARS_PATH,
    parse_quarter_end_dates_override,
)
from src.market.pipeline import format_market_dry_run_lines, format_point_in_time_dry_run_lines
from src.market.stock_prices import StockPriceError
from src.paths import DEFAULT_SUMMARY_OUTPUT
from src.pipeline.point_in_time import PointInTimeConfig, PointInTimeError
from src.pipeline.runner import run_pipeline

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_OUTPUT = str(DEFAULT_SUMMARY_OUTPUT)

PIT_EPILOG = """
Point-in-time modes reduce data leakage by capping inputs at the filing as-of date.
Instructions reduce but do not eliminate LLM training-knowledge leakage; for research
backtests requiring maximum purity, prefer documents-only mode and historically frozen
price snapshots.

Examples:
  py -3 main.py --filings-root data/filings --companies NVDA --quarter FY2026-Q1 --point-in-time --output out.xlsx
  py -3 main.py --filings-root data/filings --companies NVDA --quarter FY2026-Q1 --ticker NVDA --point-in-time-with-prices --output out.xlsx
  py -3 main.py ... --point-in-time-with-prices --unadjusted-prices
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze SEC filings for next-quarter confidence scores.",
        epilog=PIT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--filings-root",
        required=True,
        help="Root folder containing {TICKER}/{quarter}/ filing trees",
    )
    parser.add_argument(
        "--companies",
        required=True,
        help="Comma-separated tickers (e.g. NVDA,AMZN)",
    )
    parser.add_argument(
        "--quarter",
        required=True,
        help=(
            "Quarter label for all companies (e.g. FY2026-Q1). "
            "Comma-separated for multiple quarters in one export "
            "(e.g. FY2026-Q1,FY2026-Q2,FY2026-Q3,FY2026-Q4)."
        ),
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output path, .xlsx or .csv (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Anthropic model ID (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--ticker",
        help=(
            "Stock ticker for prior-quarter price lookup on single-company runs. "
            "Use --with-prices for multi-company runs (each package ticker)."
        ),
    )
    parser.add_argument(
        "--with-prices",
        action="store_true",
        help="Include prior-quarter stock prices using each company's ticker",
    )
    parser.add_argument(
        "--single-sheet",
        action="store_true",
        help="Write all companies to one Excel worksheet (default: one sheet per company)",
    )
    parser.add_argument(
        "--quarter-end-dates",
        help="Override quarter-end dates as FY2025-Q2:2024-07-28,FY2025-Q3:2024-10-27,...",
    )
    parser.add_argument(
        "--fiscal-calendars",
        default=str(DEFAULT_FISCAL_CALENDARS_PATH),
        help="Path to fiscal calendar YAML (default: config/fiscal_calendars.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate filing folders without calling the API",
    )
    parser.add_argument(
        "--skip-rescue-judge",
        action="store_true",
        help="Drop paraphrased excerpts without AI rescue (strict verbatim only)",
    )
    parser.add_argument(
        "--max-corpus-chars",
        type=int,
        default=DEFAULT_MAX_CORPUS_CHARS,
        help=(
            "Final hard cap on characters sent to the LLM after excerpt pull "
            f"(default: {DEFAULT_MAX_CORPUS_CHARS:,})"
        ),
    )
    parser.add_argument(
        "--excerpt-mode",
        default="smart",
        choices=["smart", "full", "off"],
        help="Excerpt pull mode: smart (default), full/off send entire sanitized corpus",
    )
    parser.add_argument(
        "--max-analysis-chars",
        type=int,
        default=DEFAULT_MAX_ANALYSIS_CHARS,
        help=(
            "Max characters in the analysis corpus per company when excerpt-mode=smart "
            f"(default: {DEFAULT_MAX_ANALYSIS_CHARS:,})"
        ),
    )
    parser.add_argument(
        "--write-excerpt-audit",
        action="store_true",
        help="Write pulled excerpt corpus to output_confidence/excerpt_audit/",
    )
    parser.add_argument(
        "--point-in-time",
        action="store_true",
        help="Strict documents-only scoring: no prices, no rescue judge, temporal prompt",
    )
    parser.add_argument(
        "--point-in-time-with-prices",
        action="store_true",
        help="Strict mode with 4 prior quarter-end prices capped at as-of date",
    )
    parser.add_argument(
        "--unadjusted-prices",
        action="store_true",
        help="Fetch raw closes instead of adjusted (only with --point-in-time-with-prices)",
    )
    return parser


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _build_excerpt_config(args: argparse.Namespace) -> ExcerptConfig:
    return ExcerptConfig(
        mode=normalize_excerpt_mode(args.excerpt_mode),
        max_analysis_chars=args.max_analysis_chars,
        write_audit=args.write_excerpt_audit,
    )


def _resolve_point_in_time_config(args: argparse.Namespace) -> PointInTimeConfig:
    if args.point_in_time and args.point_in_time_with_prices:
        raise SystemExit(
            "Error: --point-in-time and --point-in-time-with-prices are mutually exclusive."
        )
    if args.unadjusted_prices and not args.point_in_time_with_prices:
        raise SystemExit(
            "Error: --unadjusted-prices requires --point-in-time-with-prices."
        )
    if args.point_in_time_with_prices:
        return PointInTimeConfig.with_prices(unadjusted=args.unadjusted_prices)
    if args.point_in_time:
        return PointInTimeConfig.document_only()
    return PointInTimeConfig.disabled()


def main() -> int:
    load_dotenv()
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    try:
        point_in_time = _resolve_point_in_time_config(args)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    filings_root = Path(args.filings_root)
    date_overrides = (
        parse_quarter_end_dates_override(args.quarter_end_dates)
        if args.quarter_end_dates
        else None
    )
    fiscal_calendars_path = Path(args.fiscal_calendars)
    excerpt_config = _build_excerpt_config(args)

    if args.dry_run:
        report = dry_run_report(
            filings_root,
            companies=args.companies,
            quarter=args.quarter,
            require_as_of_date=point_in_time.active,
            excerpt_config=excerpt_config,
        )
        extra_lines: list[str] = []
        try:
            packages = []
            for normalized_quarter in parse_quarters_list(args.quarter):
                packages.extend(
                    load_filing_packages(
                        filings_root,
                        companies=args.companies,
                        quarter=normalized_quarter,
                        require_as_of_date=point_in_time.active,
                        excerpt_config=excerpt_config,
                    )
                )
        except FilingLoadError:
            packages = []

        if packages and point_in_time.active:
            package = packages[0]
            if package.as_of_date is not None:
                extra_lines = format_point_in_time_dry_run_lines(
                    as_of_date=package.as_of_date,
                    reported_quarter=package.quarter,
                    point_in_time=point_in_time,
                    ticker=args.ticker or package.ticker,
                    calendars_path=fiscal_calendars_path,
                    date_overrides=date_overrides,
                )
        elif packages and args.ticker:
            package = packages[0]
            if package.as_of_date is not None:
                extra_lines = format_market_dry_run_lines(
                    ticker=args.ticker,
                    as_of_date=package.as_of_date,
                    reported_quarter=package.quarter,
                    calendars_path=fiscal_calendars_path,
                    date_overrides=date_overrides,
                )

        if extra_lines:
            report = "\n".join([report, "", *extra_lines])
        print(report)
        return 0

    if point_in_time.include_prices and not args.ticker and not args.with_prices:
        print(
            "Error: --point-in-time-with-prices requires --ticker.",
            file=sys.stderr,
        )
        return 1

    if args.with_prices and args.ticker and "," in args.companies:
        logging.warning(
            "Ignoring --ticker for multi-company run; using each company's ticker."
        )
        effective_ticker = None
    elif args.with_prices and not args.ticker:
        effective_ticker = None
    else:
        effective_ticker = args.ticker
    if point_in_time.active and not point_in_time.include_prices and args.ticker:
        logging.warning("Ignoring --ticker in point-in-time mode (documents-only).")
        effective_ticker = None

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 1

    skip_rescue = args.skip_rescue_judge or point_in_time.active

    if point_in_time.active:
        mode = (
            "point-in-time-with-prices"
            if point_in_time.include_prices
            else "point-in-time (documents-only)"
        )
        logging.info(
            "Point-in-time mode: %s (rescue=off, prices=%s)",
            mode,
            point_in_time.include_prices,
        )

    client = AnthropicClient(api_key=api_key, model=args.model, max_retries=1)
    logging.info(
        "Starting pipeline for %s companies=%s quarter=%s",
        filings_root,
        args.companies,
        args.quarter,
    )
    try:
        rows = run_pipeline(
            client=client,
            filings_root=filings_root,
            companies=args.companies,
            quarter=args.quarter,
            skip_rescue_judge=skip_rescue,
            ticker=effective_ticker,
            with_prices=args.with_prices or bool(effective_ticker),
            fiscal_calendars_path=fiscal_calendars_path,
            quarter_end_date_overrides=date_overrides,
            point_in_time=point_in_time,
            max_corpus_chars=args.max_corpus_chars,
            excerpt_config=excerpt_config,
        )
    except (PointInTimeError, ValueError, FilingLoadError, StockPriceError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    write_output(rows, output_path, single_sheet=args.single_sheet)
    logging.info("Wrote %s rows to %s", len(rows), output_path)
    logging.info(client.usage_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
