from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.export.csv_writer import write_batch_excel, write_output
from src.batch.historical_runner import run_historical_batch
from src.enrichment.enrichment_runner import run_batch_enrichment
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
from src.market.constants import BATCH_PRIOR_QUARTER_PRICE_COUNT, PRIOR_QUARTER_PRICE_COUNT
from src.market.fiscal_calendar import (
    DEFAULT_FISCAL_CALENDARS_PATH,
    parse_quarter_end_dates_override,
)
from src.market.pipeline import format_market_dry_run_lines
from src.market.quarter_labels import batch_quarter_labels_for_ticker
from src.paths import DEFAULT_DOCUMENTS_ROOT, DEFAULT_SUMMARY_OUTPUT
from src.batch.models import BatchQuarterResult
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
        help=(
            "Drop paraphrased excerpts without AI rescue (strict verbatim only). "
            "Batch mode skips rescue judge by default; use --enable-rescue-judge to opt in."
        ),
    )
    parser.add_argument(
        "--enable-rescue-judge",
        action="store_true",
        help="Enable rescue-judge LLM calls in batch mode (default: skipped for speed/reliability)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Run historical batch backtest across many quarters (requires --ticker)",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=10,
        help="Years of calendar quarters for batch mode (default: 10 → 40 quarters)",
    )
    parser.add_argument(
        "--end-quarter",
        help="Last calendar quarter label for batch mode (default: latest completed quarter)",
    )
    parser.add_argument(
        "--batch-quarters",
        type=int,
        help="Override number of calendar quarters in batch mode (default: years * 4)",
    )
    parser.add_argument(
        "--batch-price-quarters",
        type=int,
        default=BATCH_PRIOR_QUARTER_PRICE_COUNT,
        help=(
            "Prior quarter-end prices per batch row "
            f"(default: {BATCH_PRIOR_QUARTER_PRICE_COUNT})"
        ),
    )
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=120.0,
        help="Anthropic API request timeout in seconds for batch mode (default: 120)",
    )
    parser.add_argument(
        "--enrich-transcripts",
        action="store_true",
        help="Run transcript enrichment after batch scoring (separate sheet; no score impact)",
    )
    parser.add_argument(
        "--enrich-only",
        action="store_true",
        help="Skip confidence LLM; only fetch transcripts and run enrichment",
    )
    parser.add_argument(
        "--no-web-discovery",
        action="store_true",
        help="Structured transcript sources only (local cache, SEC exhibits)",
    )
    parser.add_argument(
        "--web-discovery",
        action="store_true",
        help="Enable web-assisted transcript discovery when v2 is available",
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


def _run_batch_mode(args: argparse.Namespace) -> int:
    if not args.ticker:
        print("Error: --ticker is required for batch mode.", file=sys.stderr)
        return 1

    date_overrides = (
        parse_quarter_end_dates_override(args.quarter_end_dates)
        if args.quarter_end_dates
        else None
    )
    fiscal_calendars_path = Path(args.fiscal_calendars)
    ticker_folder = (
        resolve_ticker_folder(Path(args.documents), args.ticker)
        if args.documents
        else ticker_documents_folder(args.ticker)
    )

    client = None
    if not args.dry_run:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.",
                file=sys.stderr,
            )
            return 1
        client = AnthropicClient(
            api_key=api_key,
            model=args.model,
            max_retries=1,
            timeout_seconds=args.llm_timeout,
        )

    skip_rescue_judge = not args.enable_rescue_judge
    if args.skip_rescue_judge:
        skip_rescue_judge = True

    quarter_count = args.batch_quarters if args.batch_quarters is not None else args.years * 4
    quarter_labels = batch_quarter_labels_for_ticker(
        args.ticker,
        quarter_count,
        end_label=args.end_quarter,
        calendars_path=fiscal_calendars_path,
    )
    allow_web_discovery = args.web_discovery and not args.no_web_discovery

    if args.enrich_only:
        if args.dry_run:
            for quarter_label in quarter_labels:
                print(f"{quarter_label}: enrich-only (no confidence LLM)")
            return 0
        results = [
            BatchQuarterResult(quarter_label=label, status="success")
            for label in quarter_labels
        ]
    else:
        logging.info(
            "Starting batch backtest for %s (%s years, end=%s)",
            args.ticker,
            args.years,
            args.end_quarter or "latest completed quarter",
        )
        results = run_historical_batch(
            client,
            ticker=args.ticker,
            years=args.years,
            end_quarter=args.end_quarter,
            quarter_count=args.batch_quarters,
            price_history_quarters=args.batch_price_quarters,
            skip_rescue_judge=skip_rescue_judge,
            fetch=args.fetch,
            force_fetch=args.force_fetch,
            dry_run=args.dry_run,
            fiscal_calendars_path=fiscal_calendars_path,
            quarter_end_date_overrides=date_overrides,
            ticker_folder=ticker_folder,
        )

    success_count = sum(1 for item in results if item.status == "success" and item.summary)
    failed_count = sum(1 for item in results if item.status == "failed")
    skipped_count = sum(1 for item in results if item.status == "skipped")
    if not args.enrich_only:
        logging.info(
            "Batch complete: %s quarters — %s scored, %s failed (Edgar/load), "
            "%s skipped (retry exhausted)",
            len(results),
            success_count,
            failed_count,
            skipped_count,
        )
    if skipped_count:
        skipped_labels = ", ".join(
            item.quarter_label for item in results if item.status == "skipped"
        )
        logging.info("Skipped: %s", skipped_labels)
        print(f"Skipped: {skipped_labels}")
    if failed_count:
        failed_labels = ", ".join(
            item.quarter_label for item in results if item.status == "failed"
        )
        logging.info("Failed (no retry): %s", failed_labels)
        print(f"Failed (no retry): {failed_labels}")

    if args.dry_run and not args.enrich_only:
        for item in results:
            cutoff = item.knowledge_cutoff.isoformat() if item.knowledge_cutoff else "n/a"
            print(f"{item.quarter_label}: {item.status} (cutoff={cutoff})")
        return 0

    enrichment_results = None
    if (args.enrich_transcripts or args.enrich_only) and client is not None:
        enrichment_results = run_batch_enrichment(
            client,
            ticker=args.ticker,
            quarter_labels=quarter_labels,
            allow_web_discovery=allow_web_discovery,
        )
        enrichment_by_quarter = {item.quarter: item for item in enrichment_results}
        for result in results:
            result.enrichment = enrichment_by_quarter.get(result.quarter_label)

    output_path = Path(args.output)
    if output_path.suffix.lower() != ".xlsx":
        output_path = output_path.with_suffix(".xlsx")
    write_batch_excel(results, output_path, enrichment_results=enrichment_results)
    logging.info("Wrote batch workbook to %s", output_path)
    if client is not None:
        logging.info(client.usage_summary())
    return 0


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

    if args.batch:
        return _run_batch_mode(args)

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
