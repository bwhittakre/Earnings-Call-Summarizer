"""Run AMZN quarters one at a time with retries and checkpoint resume."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export.csv_writer import sort_quarter_summaries, write_output
from src.ingest.filings import FilingLoadError
from src.llm.anthropic_client import AnthropicClient
from src.market.stock_prices import StockPriceError
from src.pipeline.runner import run_pipeline
from src.schemas.models import QuarterSummary

DEFAULT_MODEL = "claude-sonnet-4-6"
ROOT = Path("AMZN/Amazon")
CHECKPOINT = Path("output_confidence/amzn_40q_checkpoint.json")
OUTPUT = Path("output_confidence/amzn_fy2017_2026_all_quarters_with_prices.xlsx")


def discover_quarters() -> list[str]:
    quarters: list[str] = []
    for fiscal_year in sorted(ROOT.iterdir()):
        if not fiscal_year.is_dir():
            continue
        for quarter_dir in sorted(fiscal_year.iterdir()):
            if quarter_dir.is_dir() and "-Q" in quarter_dir.name:
                quarters.append(quarter_dir.name)
    return quarters


def load_checkpoint(path: Path) -> dict[str, QuarterSummary]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        quarter: QuarterSummary.model_validate(data)
        for quarter, data in payload.get("completed", {}).items()
    }


def save_checkpoint(path: Path, completed: dict[str, QuarterSummary]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "completed": {
            quarter: summary.model_dump()
            for quarter, summary in completed.items()
        }
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_quarter_with_retries(
    client: AnthropicClient,
    quarter: str,
    *,
    max_attempts: int,
) -> list[QuarterSummary]:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return run_pipeline(
                client,
                Path("."),
                companies="AMZN",
                quarter=quarter,
                ticker="AMZN",
                with_prices=True,
            )
        except (ValueError, FilingLoadError, StockPriceError) as exc:
            last_error = exc
            logging.warning(
                "Attempt %s/%s failed for %s: %s",
                attempt,
                max_attempts,
                quarter,
                exc,
            )
            if attempt < max_attempts:
                time.sleep(5)
    raise RuntimeError(f"All {max_attempts} attempts failed for {quarter}") from last_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        return 1

    quarters = discover_quarters()
    completed = load_checkpoint(args.checkpoint)
    pending = [q for q in quarters if q not in completed]

    logging.info(
        "Batch: %s total, %s done, %s pending",
        len(quarters),
        len(completed),
        len(pending),
    )

    client = AnthropicClient(api_key=api_key, model=args.model, max_retries=2)
    failed: list[tuple[str, str]] = []

    for quarter in pending:
        logging.info("Processing %s", quarter)
        try:
            rows = run_quarter_with_retries(
                client,
                quarter,
                max_attempts=args.max_attempts,
            )
        except RuntimeError as exc:
            failed.append((quarter, str(exc)))
            logging.error("Skipping %s after retries: %s", quarter, exc)
            continue

        completed[quarter] = rows[0]
        save_checkpoint(args.checkpoint, completed)
        logging.info(
            "Completed %s (%s/%s) confidence=%s",
            quarter,
            len(completed),
            len(quarters),
            rows[0].confidence_score,
        )

    if not completed:
        logging.error("No quarters completed.")
        return 1

    summaries = sort_quarter_summaries(list(completed.values()))
    write_output(summaries, args.output, single_sheet=True)
    logging.info("Wrote %s rows to %s", len(summaries), args.output)
    if failed:
        logging.error("Failed quarters (%s): %s", len(failed), ", ".join(q for q, _ in failed))
        for quarter, message in failed:
            logging.error("  %s: %s", quarter, message)
    logging.info(client.usage_summary())
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
