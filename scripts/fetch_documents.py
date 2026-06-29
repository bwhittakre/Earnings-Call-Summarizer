#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.ingest.documents.cache import ticker_documents_folder
from src.ingest.documents.loader import dry_run_documents_report, resolve_ticker_folder
from src.ingest.documents.models import FetchRequest
from src.ingest.documents.orchestrator import fetch_quarter_documents
from src.market.fiscal_calendar import (
    DEFAULT_FISCAL_CALENDARS_PATH,
    parse_quarter_end_dates_override,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch SEC document bundle for one quarter.")
    parser.add_argument("--ticker", required=True, help="Stock ticker (e.g. NVDA)")
    parser.add_argument("--quarter", required=True, help="Quarter label (e.g. FY2025-Q2)")
    parser.add_argument(
        "--documents",
        help="Ticker documents folder (default: data/documents/{ticker})",
    )
    parser.add_argument("--force-fetch", action="store_true", help="Re-download cached files")
    parser.add_argument(
        "--fiscal-calendars",
        default=str(DEFAULT_FISCAL_CALENDARS_PATH),
        help="Path to fiscal calendar YAML",
    )
    parser.add_argument(
        "--quarter-end-dates",
        help="Override quarter-end dates as FY2025-Q2:2024-07-28,...",
    )
    return parser


def main() -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    date_overrides = (
        parse_quarter_end_dates_override(args.quarter_end_dates)
        if args.quarter_end_dates
        else None
    )
    documents_path = Path(args.documents) if args.documents else ticker_documents_folder(args.ticker)
    ticker_folder = (
        resolve_ticker_folder(documents_path, args.ticker)
        if args.documents
        else ticker_documents_folder(args.ticker)
    )
    fetch_quarter_documents(
        FetchRequest(ticker=args.ticker, quarter_label=args.quarter),
        force=args.force_fetch,
        ticker_folder=ticker_folder,
        calendars_path=Path(args.fiscal_calendars),
        date_overrides=date_overrides,
    )
    print(
        dry_run_documents_report(
            documents_path,
            ticker=args.ticker,
            quarter=args.quarter,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
