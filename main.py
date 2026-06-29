from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.export.csv_writer import write_output
from src.ingest.documents.cache import ticker_documents_folder
from src.ingest.documents.loader import (
    dry_run_documents_report,
    load_quarter_documents,
    resolve_ticker_folder,
)
from src.ingest.documents.models import FetchRequest
from src.ingest.documents.orchestrator import fetch_quarter_documents
from src.ingest.loader import dry_run_report, resolve_transcript_files
from src.llm.anthropic_client import AnthropicClient
from src.market.constants import PRIOR_QUARTER_PRICE_COUNT
from src.market.fiscal_calendar import (
    DEFAULT_FISCAL_CALENDARS_PATH,
    parse_quarter_end_dates_override,
)
from src.market.pipeline import format_market_dry_run_lines
from src.paths import DEFAULT_DOCUMENTS_ROOT, DEFAULT_SUMMARY_OUTPUT
from src.pipeline.runner import run_document_pipeline, run_pipeline

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_OUTPUT = str(DEFAULT_SUMMARY_OUTPUT)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize earnings documents or transcripts with evidence-backed confidence scoring."
        )
    )
    parser.add_argument(
        "--transcripts",
        help="Legacy transcript folder or single transcript file",
    )
    parser.add_argument(
        "--documents",
        help=(
            "Document bundle folder (default with --fetch: "
            f"{DEFAULT_DOCUMENTS_ROOT}/{{ticker}})"
        ),
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch SEC/IR document bundle before analysis (requires --ticker and --quarter)",
    )
    parser.add_argument(
        "--force-fetch",
        action="store_true",
        help="Re-download documents even if cached",
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
        help="Expected number of quarterly inputs (default: 1; transcript mode only)",
    )
    parser.add_argument(
        "--quarter",
        help="Quarter label (e.g. FY2025-Q2). Required for document mode.",
    )
    parser.add_argument(
        "--ticker",
        help="Stock ticker for document fetch and prior-quarter price lookup (e.g. NVDA)",
    )
    parser.add_argument(
        "--reported-quarter",
        help="Override reported quarter parsed from source text (e.g. 2025-Q4 or FY2025-Q4).",
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
        "--price-history-quarters",
        type=int,
        default=PRIOR_QUARTER_PRICE_COUNT,
        help=(
            "Number of prior quarter-end stock prices to fetch when --ticker is set "
            f"(default: {PRIOR_QUARTER_PRICE_COUNT}, i.e. 2 years)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs without calling the API",
    )
    parser.add_argument(
        "--skip-rescue-judge",
        action="store_true",
        help="Drop paraphrased excerpts without AI rescue (strict verbatim only)",
    )
    return parser


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _document_mode(args: argparse.Namespace) -> bool:
    return bool(args.documents or args.fetch)


def _resolve_documents_path(args: argparse.Namespace) -> Path:
    if args.documents:
        return Path(args.documents)
    if not args.ticker:
        raise ValueError("--ticker is required for document fetch mode")
    return ticker_documents_folder(args.ticker)


def _resolve_ticker_folder(args: argparse.Namespace, documents_path: Path) -> Path:
    if args.documents:
        return resolve_ticker_folder(documents_path, args.ticker)
    return ticker_documents_folder(args.ticker)


def _load_single_source_text(transcript_path: Path, quarter: str | None) -> str | None:
    assigned = resolve_transcript_files(transcript_path, quarter=quarter)
    if len(assigned) != 1:
        return None
    return assigned[0].path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    load_dotenv()
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    document_mode = _document_mode(args)
    if not document_mode and not args.transcripts:
        print(
            "Error: provide --transcripts (legacy) or --documents / --fetch (SEC document mode).",
            file=sys.stderr,
        )
        return 1
    if document_mode:
        if not args.ticker:
            print("Error: --ticker is required for document mode.", file=sys.stderr)
            return 1
        if not args.quarter:
            print("Error: --quarter is required for document mode.", file=sys.stderr)
            return 1

    date_overrides = (
        parse_quarter_end_dates_override(args.quarter_end_dates)
        if args.quarter_end_dates
        else None
    )
    fiscal_calendars_path = Path(args.fiscal_calendars)

    if document_mode:
        documents_path = _resolve_documents_path(args)
        ticker_folder = _resolve_ticker_folder(args, documents_path)
        if args.fetch or args.force_fetch:
            fetch_quarter_documents(
                FetchRequest(ticker=args.ticker, quarter_label=args.quarter),
                force=args.force_fetch,
                ticker_folder=ticker_folder,
                calendars_path=fiscal_calendars_path,
                date_overrides=date_overrides,
            )

        if args.dry_run:
            report = dry_run_documents_report(
                documents_path,
                ticker=args.ticker,
                quarter=args.quarter,
            )
            loaded = load_quarter_documents(
                documents_path,
                ticker=args.ticker,
                quarter=args.quarter,
                ticker_folder=ticker_folder,
            )
            if args.ticker:
                report = "\n".join(
                    [
                        report,
                        "",
                        *format_market_dry_run_lines(
                            ticker=args.ticker,
                            transcript_text=loaded.corpus_text,
                            reported_quarter=args.reported_quarter,
                            calendars_path=fiscal_calendars_path,
                            date_overrides=date_overrides,
                            price_history_quarters=args.price_history_quarters,
                        ),
                    ]
                )
            print(report)
            return 0

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.",
                file=sys.stderr,
            )
            return 1

        client = AnthropicClient(api_key=api_key, model=args.model, max_retries=1)
        logging.info(
            "Starting document pipeline for %s %s at %s",
            args.ticker,
            args.quarter,
            documents_path,
        )
        rows = run_document_pipeline(
            client=client,
            documents_path=documents_path,
            ticker=args.ticker,
            quarter=args.quarter,
            skip_rescue_judge=args.skip_rescue_judge,
            fiscal_calendars_path=fiscal_calendars_path,
            quarter_end_date_overrides=date_overrides,
            reported_quarter_override=args.reported_quarter,
            price_history_quarters=args.price_history_quarters,
        )
    else:
        transcript_path = Path(args.transcripts)
        if args.dry_run:
            report = dry_run_report(transcript_path, args.quarters, args.quarter)
            if args.ticker:
                transcript_text = _load_single_source_text(transcript_path, args.quarter)
                if transcript_text:
                    report = "\n".join(
                        [
                            report,
                            "",
                            *format_market_dry_run_lines(
                                ticker=args.ticker,
                                transcript_text=transcript_text,
                                reported_quarter=args.reported_quarter,
                                calendars_path=fiscal_calendars_path,
                                date_overrides=date_overrides,
                                price_history_quarters=args.price_history_quarters,
                            ),
                        ]
                    )
                else:
                    report = "\n".join(
                        [
                            report,
                            "",
                            "Market data: SKIPPED (select exactly one transcript for date preview)",
                        ]
                    )
            print(report)
            return 0

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.",
                file=sys.stderr,
            )
            return 1

        client = AnthropicClient(api_key=api_key, model=args.model, max_retries=1)
        logging.info("Starting pipeline for %s", transcript_path)
        rows = run_pipeline(
            client=client,
            transcript_path=str(transcript_path),
            expected_quarters=args.quarters,
            quarter=args.quarter,
            skip_rescue_judge=args.skip_rescue_judge,
            ticker=args.ticker,
            fiscal_calendars_path=fiscal_calendars_path,
            quarter_end_date_overrides=date_overrides,
            reported_quarter_override=args.reported_quarter,
            price_history_quarters=args.price_history_quarters,
        )

    output_path = Path(args.output)
    write_output(rows, output_path)
    logging.info("Wrote %s rows to %s", len(rows), output_path)
    logging.info(client.usage_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
