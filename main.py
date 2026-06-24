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
from src.pipeline.runner import run_company_pipeline

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_OUTPUT = "./output/summary.xlsx"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize earnings call transcripts for one or two companies."
    )
    parser.add_argument("--company-a", required=True, help="Display name for company A")
    parser.add_argument(
        "--transcripts-a", required=True, help="Folder with transcript files for company A"
    )
    parser.add_argument(
        "--company-b",
        help="Display name for company B (optional; omit to run company A only)",
    )
    parser.add_argument(
        "--transcripts-b",
        help="Folder with transcript files for company B (required if --company-b is set)",
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
        default=8,
        help="Expected number of quarterly transcripts per company (default: 8)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate transcript folders without calling the API",
    )
    parser.add_argument(
        "--skip-rollup",
        action="store_true",
        help="Produce quarter summaries only (no company rollup)",
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

    if bool(args.company_b) != bool(args.transcripts_b):
        print(
            "Error: provide both --company-b and --transcripts-b, or omit both to run one company.",
            file=sys.stderr,
        )
        return 1

    companies = [(args.company_a, Path(args.transcripts_a))]
    if args.company_b:
        companies.append((args.company_b, Path(args.transcripts_b)))

    if args.dry_run:
        for name, folder in companies:
            print(dry_run_report(name, folder, args.quarters))
            print()
        return 0

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.",
            file=sys.stderr,
        )
        return 1

    client = AnthropicClient(api_key=api_key, model=args.model, max_retries=1)
    all_rows = []

    for name, folder in companies:
        logging.info("Starting pipeline for %s", name)
        rows = run_company_pipeline(
            client=client,
            company_name=name,
            transcript_folder=str(folder),
            expected_quarters=args.quarters,
            skip_rollup=args.skip_rollup,
            skip_rescue_judge=args.skip_rescue_judge,
        )
        all_rows.extend(rows)

    output_path = Path(args.output)
    write_output(all_rows, output_path)
    logging.info("Wrote %s rows to %s", len(all_rows), output_path)
    logging.info(client.usage_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
