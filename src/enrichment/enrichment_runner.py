from __future__ import annotations

import logging

from src.enrichment.models import EnrichmentResult
from src.enrichment.transcript_fetcher import fetch_transcript
from src.llm.anthropic_client import AnthropicClient, load_prompt
from src.paths import DEFAULT_TRANSCRIPTS_ROOT
from src.schemas.models import EvidenceClaim
from pydantic import BaseModel, Field
from typing import Literal

logger = logging.getLogger(__name__)


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
    return EnrichmentResult(
        quarter=quarter_label,
        positives=response.positives,
        negatives=response.negatives,
        key_quotes=response.key_quotes,
        availability=response.availability,
        notes=notes,
    )


def run_batch_enrichment(
    client: AnthropicClient,
    *,
    ticker: str,
    quarter_labels: list[str],
    allow_web_discovery: bool = False,
) -> list[EnrichmentResult]:
    results: list[EnrichmentResult] = []
    for quarter_label in quarter_labels:
        logger.info("Enriching transcript for %s %s", ticker, quarter_label)
        try:
            results.append(
                run_quarter_enrichment(
                    client,
                    ticker=ticker,
                    quarter_label=quarter_label,
                    allow_web_discovery=allow_web_discovery,
                )
            )
        except Exception as exc:
            logger.warning("Enrichment failed for %s: %s", quarter_label, exc)
            results.append(
                EnrichmentResult(
                    quarter=quarter_label,
                    availability="missing",
                    notes=f"Enrichment error: {exc}",
                )
            )
    return results
