from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.export.csv_writer import write_output
from src.ingest.loader import dry_run_report, resolve_transcript_files
from src.ingest.reported_quarter import ReportedQuarterError
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
Point-in-time modes reduce data leakage by capping inputs at the earnings call date.
Instructions reduce but do not eliminate LLM training-knowledge leakage; for research
backtests requiring maximum purity, prefer transcript-only mode and historically frozen
price snapshots.

Examples:
  py -3 main.py --transcripts file.txt --point-in-time --output out.xlsx
  py -3 main.py --transcripts file.txt --ticker NVDA --point-in-time-with-prices --output out.xlsx
  py -3 main.py ... --point-in-time-with-prices --unadjusted-prices
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize earnings call transcripts with auto-detected company labeling.",
        epilog=PIT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--transcripts",
        required=True,
        help="Transcript folder or single transcript file",
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
        "--quarters",
        type=int,
        default=1,
        help="Expected number of quarterly transcripts (default: 1)",
    )
    parser.add_argument(
        "--quarter",
        help="Load only this quarter from a folder (e.g. FY2025-Q2). Ignored for single-file paths unless checking a match.",
    )
    parser.add_argument(
        "--ticker",
        help="Stock ticker for prior-quarter price lookup (e.g. NVDA). Enables market data input.",
    )
    parser.add_argument(
        "--reported-quarter",
        help="Override reported quarter parsed from transcript (e.g. 2025-Q4 or FY2025-Q4). "
        "Not allowed with point-in-time modes.",
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
        help="Validate transcript paths without calling the API",
    )
    parser.add_argument(
        "--skip-rescue-judge",
        action="store_true",
        help="Drop paraphrased excerpts without AI rescue (strict verbatim only)",
    )
    parser.add_argument(
        "--point-in-time",
        action="store_true",
        help="Strict transcript-only scoring: no prices, no rescue judge, temporal prompt",
    )
    parser.add_argument(
        "--point-in-time-with-prices",
        action="store_true",
        help="Strict mode with 4 prior quarter-end prices capped at call date",
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


def _load_single_transcript_text(transcript_path: Path, quarter: str | None) -> str | None:
    assigned = resolve_transcript_files(transcript_path, quarter=quarter)
    if len(assigned) != 1:
        return None
    return assigned[0].path.read_text(encoding="utf-8", errors="replace")


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
        return PointInTimeConfig.transcript_only()
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

    if point_in_time.active and args.reported_quarter:
        print(
            "Error: --reported-quarter is not allowed in point-in-time mode.",
            file=sys.stderr,
        )
        return 1

    transcript_path = Path(args.transcripts)
    date_overrides = (
        parse_quarter_end_dates_override(args.quarter_end_dates)
        if args.quarter_end_dates
        else None
    )
    fiscal_calendars_path = Path(args.fiscal_calendars)

    if args.dry_run:
        report = dry_run_report(transcript_path, args.quarters, args.quarter)
        assigned = resolve_transcript_files(transcript_path, quarter=args.quarter)
        transcript_text = (
            assigned[0].path.read_text(encoding="utf-8", errors="replace")
            if len(assigned) == 1
            else None
        )
        filename_quarter = assigned[0].quarter if len(assigned) == 1 else None

        extra_lines: list[str] = []
        if point_in_time.active and transcript_text and filename_quarter:
            extra_lines = format_point_in_time_dry_run_lines(
                transcript_text=transcript_text,
                filename_quarter=filename_quarter,
                point_in_time=point_in_time,
                ticker=args.ticker,
                reported_quarter_override=args.reported_quarter,
                calendars_path=fiscal_calendars_path,
                date_overrides=date_overrides,
            )
        elif args.ticker and transcript_text:
            extra_lines = format_market_dry_run_lines(
                ticker=args.ticker,
                transcript_text=transcript_text,
                filename_quarter=filename_quarter,
                reported_quarter=args.reported_quarter,
                calendars_path=fiscal_calendars_path,
                date_overrides=date_overrides,
            )
        elif args.ticker:
            extra_lines = [
                "Market data: SKIPPED (select exactly one transcript for date preview)"
            ]

        if extra_lines:
            report = "\n".join([report, "", *extra_lines])
        print(report)
        return 0

    if point_in_time.include_prices and not args.ticker:
        print(
            "Error: --point-in-time-with-prices requires --ticker.",
            file=sys.stderr,
        )
        return 1

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 1

    skip_rescue = args.skip_rescue_judge or point_in_time.active
    effective_ticker = args.ticker
    if point_in_time.active and not point_in_time.include_prices and args.ticker:
        logging.warning("Ignoring --ticker in point-in-time mode (transcript-only).")
        effective_ticker = None

    if point_in_time.active:
        mode = (
            "point-in-time-with-prices"
            if point_in_time.include_prices
            else "point-in-time (transcript-only)"
        )
        logging.info(
            "Point-in-time mode: %s (rescue=off, prices=%s)",
            mode,
            point_in_time.include_prices,
        )

    client = AnthropicClient(api_key=api_key, model=args.model, max_retries=1)
    logging.info("Starting pipeline for %s", transcript_path)
    try:
        rows = run_pipeline(
            client=client,
            transcript_path=str(transcript_path),
            expected_quarters=args.quarters,
            quarter=args.quarter,
            skip_rescue_judge=skip_rescue,
            ticker=effective_ticker,
            fiscal_calendars_path=fiscal_calendars_path,
            quarter_end_date_overrides=date_overrides,
            reported_quarter_override=args.reported_quarter,
            point_in_time=point_in_time,
        )
    except (PointInTimeError, ValueError, ReportedQuarterError, StockPriceError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    write_output(rows, output_path)
    logging.info("Wrote %s rows to %s", len(rows), output_path)
    logging.info(client.usage_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
