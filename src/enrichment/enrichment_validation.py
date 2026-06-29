from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.paths import EVIDENCE_AUDIT_DIR
from src.schemas.models import EvidenceClaim
from src.validation.evidence_validator import excerpt_found_in_source
from src.validation.quote_anchor import find_verbatim_quote

ENRICHMENT_MIN_EXCERPT_LENGTH = 8


def _validate_claim_list(
    claims: list[EvidenceClaim],
    source: str,
) -> tuple[list[EvidenceClaim], list[dict]]:
    kept: list[EvidenceClaim] = []
    dropped: list[dict] = []
    for index, item in enumerate(claims):
        if excerpt_found_in_source(
            item.excerpt,
            source,
            min_length=ENRICHMENT_MIN_EXCERPT_LENGTH,
        ):
            kept.append(item)
            continue
        anchored = find_verbatim_quote(item.claim, source, hint_excerpt=item.excerpt)
        if anchored and excerpt_found_in_source(
            anchored,
            source,
            min_length=ENRICHMENT_MIN_EXCERPT_LENGTH,
        ):
            kept.append(EvidenceClaim(claim=item.claim, excerpt=anchored))
            continue
        dropped.append(
            {
                "index": index,
                "claim": item.claim,
                "excerpt": item.excerpt,
                "reason": "excerpt not found in transcript",
            }
        )
    return kept, dropped


def validate_enrichment_claims(
    *,
    positives: list[EvidenceClaim],
    negatives: list[EvidenceClaim],
    key_quotes: list[EvidenceClaim],
    transcript_text: str,
    label: str,
) -> tuple[
    list[EvidenceClaim],
    list[EvidenceClaim],
    list[EvidenceClaim],
    str,
    int,
    int,
    str | None,
]:
    validated_pos, dropped_pos = _validate_claim_list(positives, transcript_text)
    validated_neg, dropped_neg = _validate_claim_list(negatives, transcript_text)
    validated_quotes, dropped_quotes = _validate_claim_list(key_quotes, transcript_text)

    dropped = [
        *({"field": "positives", **entry} for entry in dropped_pos),
        *({"field": "negatives", **entry} for entry in dropped_neg),
        *({"field": "key_quotes", **entry} for entry in dropped_quotes),
    ]
    kept_count = len(validated_pos) + len(validated_neg) + len(validated_quotes)
    dropped_count = len(dropped)

    audit_path: Path | None = None
    if dropped or kept_count:
        EVIDENCE_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_label = label.replace("/", "_").replace("\\", "_")
        audit_path = EVIDENCE_AUDIT_DIR / f"{safe_label}_enrichment_{timestamp}.json"
        audit_path.write_text(
            json.dumps(
                {
                    "label": label,
                    "kept_count": kept_count,
                    "dropped_count": dropped_count,
                    "dropped": dropped,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    if kept_count == 0 and transcript_text.strip():
        status = "all dropped"
    elif dropped_count:
        status = f"kept={kept_count} dropped={dropped_count}"
    else:
        status = f"kept={kept_count}"

    return (
        validated_pos,
        validated_neg,
        validated_quotes,
        status,
        kept_count,
        dropped_count,
        str(audit_path) if audit_path else None,
    )
