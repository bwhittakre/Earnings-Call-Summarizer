from __future__ import annotations

from src.schemas.models import RescueJudgeResult, RescueReview
from src.validation.evidence_processor import _review_key
from src.validation.evidence_validator import ValidationFailure, excerpt_found_in_source
from src.validation.rescue_judge import CANONICAL_RETRY_FEEDBACK, RescueJudge


def augment_rescue_reviews_with_retries(
    rescue_judge: RescueJudge,
    failures: list[ValidationFailure],
    rescue_result: RescueJudgeResult,
    source_text: str,
    label: str,
) -> RescueJudgeResult:
    """Retry single-bullet rescue when batch returned rescued but canonical fails Pass 1."""
    review_map: dict[tuple[str, int | None], RescueReview] = {
        _review_key(review.field, review.index): review for review in rescue_result.reviews
    }

    for failure in failures:
        review = review_map.get(_review_key(failure.field, failure.index))
        if not review or review.verdict != "rescued" or not review.canonical_excerpt:
            continue
        if excerpt_found_in_source(review.canonical_excerpt, source_text):
            continue

        retry_result, _ = rescue_judge.review_single_failure(
            failure,
            source_text,
            label,
            CANONICAL_RETRY_FEEDBACK,
        )
        if not retry_result.reviews:
            continue
        review_map[_review_key(failure.field, failure.index)] = retry_result.reviews[0]

    return RescueJudgeResult(reviews=list(review_map.values()))
