from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import BaseModel, Field
from typing import Literal

from src.enrichment.enrichment_validation import validate_enrichment_claims
from src.enrichment.models import EnrichmentResult
from src.enrichment.transcript_fetcher import fetch_transcript
from src.llm.anthropic_client import AnthropicClient, load_prompt
from src.paths import DEFAULT_TRANSCRIPTS_ROOT
from src.schemas.models import EvidenceClaim

logger = logging.getLogger(__name__)

DEFAULT_ENRICHMENT_WORKERS = 4


class _EnrichmentLLMResponse(BaseModel):
    positives: list[EvidenceClaim] = Field(default_factory=list)
    negatives: list[EvidenceClaim] = Field(default_factory=list)
    key_quotes: list[EvidenceClaim] = Field(default_factory=list)
    availability: Literal["found", "missing"] = "missing"


def run_quarter_enrichment(
    client: AnthropicClient,
    *,
    ticker: str,
    quarter_label: str,
    allow_web_discovery: bool = False,
) -> EnrichmentResult:
    source = fetch_transcript(
        ticker,
        quarter_label,
        transcripts_root=DEFAULT_TRANSCRIPTS_ROOT,
        allow_web_discovery=allow_web_discovery,
    )
    if source is None or not source.text.strip():
        return EnrichmentResult(
            quarter=quarter_label,
            availability="missing",
            notes="No transcript found in cache or structured sources",
        )

    system_prompt = load_prompt("transcript_enrichment.txt")
    user_content = "\n".join(
        [
            f"Quarter: {quarter_label}",
            f"Ticker: {ticker.strip().upper()}",
            "",
            "--- EARNINGS CALL TRANSCRIPT ---",
            source.text,
        ]
    )
    response, _ = client.complete_json(
        system_prompt=system_prompt,
        user_content=user_content,
        response_model=_EnrichmentLLMResponse,
        label=f"{quarter_label}_enrichment",
    )
    notes = f"Source: {source.source}"
    if source.url:
        notes = f"{notes}; URL: {source.url}"

    validated_pos, validated_neg, validated_quotes, status, kept_count, dropped_count, audit_path = (
        validate_enrichment_claims(
            positives=response.positives,
            negatives=response.negatives,
            key_quotes=response.key_quotes,
            transcript_text=source.text,
            label=f"{ticker.strip().upper()}_{quarter_label}_enrichment",
        )
    )
    availability = response.availability
    if kept_count == 0 and source.text.strip():
        availability = "missing"

    return EnrichmentResult(
        quarter=quarter_label,
        positives=validated_pos,
        negatives=validated_neg,
        key_quotes=validated_quotes,
        availability=availability,
        notes=notes,
        validation_status=status,
        kept_count=kept_count,
        dropped_count=dropped_count,
        audit_path=audit_path,
    )


def _enrich_one_quarter(
    client: AnthropicClient,
    *,
    ticker: str,
    quarter_label: str,
    allow_web_discovery: bool,
) -> EnrichmentResult:
    try:
        return run_quarter_enrichment(
            client,
            ticker=ticker,
            quarter_label=quarter_label,
            allow_web_discovery=allow_web_discovery,
        )
    except Exception as exc:
        logger.warning("Enrichment failed for %s: %s", quarter_label, exc)
        return EnrichmentResult(
            quarter=quarter_label,
            availability="missing",
            notes=f"Enrichment error: {exc}",
        )


def run_batch_enrichment(
    client: AnthropicClient,
    *,
    ticker: str,
    quarter_labels: list[str],
    allow_web_discovery: bool = False,
    enrichment_workers: int = DEFAULT_ENRICHMENT_WORKERS,
) -> list[EnrichmentResult]:
    if not quarter_labels:
        return []

    worker_count = max(1, enrichment_workers)
    logger.info(
        "Phase 4 enrichment — %s quarters with %s worker(s)",
        len(quarter_labels),
        worker_count,
    )

    results_by_quarter: dict[str, EnrichmentResult] = {}

    if worker_count == 1:
        for quarter_label in quarter_labels:
            logger.info("Enriching transcript for %s %s", ticker, quarter_label)
            results_by_quarter[quarter_label] = _enrich_one_quarter(
                client,
                ticker=ticker,
                quarter_label=quarter_label,
                allow_web_discovery=allow_web_discovery,
            )
    else:
        completed = 0
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                pool.submit(
                    _enrich_one_quarter,
                    client,
                    ticker=ticker,
                    quarter_label=quarter_label,
                    allow_web_discovery=allow_web_discovery,
                ): quarter_label
                for quarter_label in quarter_labels
            }
            for future in as_completed(futures):
                result = future.result()
                with lock:
                    completed += 1
                    results_by_quarter[result.quarter] = result
                    logger.info(
                        "Phase 4 enrichment — %s/%s complete (%s)",
                        completed,
                        len(quarter_labels),
                        result.quarter,
                    )

    return [results_by_quarter[label] for label in quarter_labels if label in results_by_quarter]
