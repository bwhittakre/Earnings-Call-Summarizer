from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.export.csv_writer import write_output
from src.ingest.loader import dry_run_report
from src.llm.anthropic_client import AnthropicClient
from src.paths import DEFAULT_SUMMARY_OUTPUT
from src.pipeline.runner import run_pipeline

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_OUTPUT = str(DEFAULT_SUMMARY_OUTPUT)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize earnings call transcripts with auto-detected company labeling."
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
        "--dry-run",
        action="store_true",
        help="Validate transcript paths without calling the API",
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


def main() -> int:
    load_dotenv()
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    transcript_path = Path(args.transcripts)

    if args.dry_run:
        print(dry_run_report(transcript_path, args.quarters, args.quarter))
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
    )

    output_path = Path(args.output)
    write_output(rows, output_path)
    logging.info("Wrote %s rows to %s", len(rows), output_path)
    logging.info(client.usage_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
