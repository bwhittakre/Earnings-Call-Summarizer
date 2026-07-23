"""Tests that build_request()/finalize() on each scorer produce the same
result as score(), and that score() still makes exactly one LLM call — the
refactor for Batch API support (Phase 2) must not change sync behavior."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

from delta_scorer import DeltaScorer, TranscriptDeltaSummary  # noqa: E402
from dimension_scorer import DimensionScorer, TranscriptDimensionSummary  # noqa: E402
from novelty_scorer import NoveltyScorer, TranscriptNoveltySummary  # noqa: E402
from surprise_scorer import SurpriseScorer, TranscriptSurpriseSummary  # noqa: E402
from transcript_providers import Transcript  # noqa: E402

from src.schemas.models import LLMResult, TokenUsage  # noqa: E402

CORPUS = "We saw strong demand in data center and raised our full-year outlook."


def _transcript(fp="FY2025-Q1", ticker="NVDA") -> Transcript:
    return Transcript(
        ticker=ticker,
        fiscal_period=fp,
        call_date="2025-02-20",
        source_name="local",
        raw_text=CORPUS,
        prepared_remarks=CORPUS,
        qa_text="",
        speakers=["CEO"],
    )


def _llm_result(usage_tokens=(10, 5)) -> LLMResult:
    return LLMResult(
        usage=TokenUsage(input_tokens=usage_tokens[0], output_tokens=usage_tokens[1]),
        raw_response="{}",
    )


class DimensionScorerBatchSplitTests(unittest.TestCase):
    def _summary(self) -> TranscriptDimensionSummary:
        return TranscriptDimensionSummary(
            company_name="Nvidia",
            ticker="NVDA",
            fiscal_period="FY2025-Q1",
            dimensions=[{"dimension": "demand", "score": 1.0, "evidence": [], "rationale": "r"}],
        )

    def test_score_calls_complete_json_once_and_matches_build_request(self):
        client = MagicMock()
        client.complete_json.return_value = (self._summary(), _llm_result())
        scorer = DimensionScorer(client, use_rescue=False)
        transcript = _transcript()

        request = scorer.build_request(transcript, "Nvidia")
        scored = scorer.score(transcript, "Nvidia")

        self.assertEqual(client.complete_json.call_count, 1)
        _, kwargs = client.complete_json.call_args
        self.assertEqual(kwargs["system_prompt"], request.system_prompt)
        self.assertEqual(kwargs["user_content"], request.user_content)
        self.assertEqual(kwargs["label"], request.custom_id)
        self.assertEqual(kwargs["response_model"], DimensionScorer.RESPONSE_MODEL)
        self.assertEqual(scored.summary.company_name, "Nvidia")

    def test_finalize_from_build_request_matches_score(self):
        client = MagicMock()
        summary = self._summary()
        llm_result = _llm_result()
        client.complete_json.return_value = (summary, llm_result)
        scorer = DimensionScorer(client, use_rescue=False)
        transcript = _transcript()

        request = scorer.build_request(transcript, "Nvidia")
        via_finalize = scorer.finalize(summary, llm_result, request.custom_id, transcript.raw_text)
        via_score = scorer.score(transcript, "Nvidia")

        self.assertEqual(via_finalize.dimensions[0].dimension, via_score.dimensions[0].dimension)
        self.assertEqual(via_finalize.dimensions[0].score, via_score.dimensions[0].score)


class DeltaScorerBatchSplitTests(unittest.TestCase):
    def _summary(self) -> TranscriptDeltaSummary:
        return TranscriptDeltaSummary(
            company_name="Nvidia",
            ticker="NVDA",
            fiscal_period="FY2025-Q2",
            prior_period="FY2025-Q1",
            deltas=[{"dimension": "demand", "change_direction": "improved", "change_magnitude": 0.5, "evidence": []}],
        )

    def test_build_request_and_score_agree(self):
        client = MagicMock()
        client.complete_json.return_value = (self._summary(), _llm_result())
        scorer = DeltaScorer(client, use_rescue=False)
        current = _transcript(fp="FY2025-Q2")

        request = scorer.build_request(
            current, "FY2025-Q1", "Nvidia", prior_summary_block="Prior quarter: FY2025-Q1"
        )
        scored = scorer.score(
            current, "FY2025-Q1", "Nvidia", prior_summary_block="Prior quarter: FY2025-Q1"
        )

        self.assertEqual(request.custom_id, "NVDA_FY2025-Q1_to_FY2025-Q2_delta")
        _, kwargs = client.complete_json.call_args
        self.assertEqual(kwargs["user_content"], request.user_content)
        self.assertEqual(scored.deltas[0].change_direction, "improved")


class SurpriseScorerBatchSplitTests(unittest.TestCase):
    def _summary(self) -> TranscriptSurpriseSummary:
        return TranscriptSurpriseSummary(
            company_name="Nvidia",
            ticker="NVDA",
            fiscal_period="FY2025-Q1",
            surprises=[{"dimension": "demand", "surprise_direction": "in_line", "surprise_magnitude": 0.0, "evidence": []}],
        )

    def test_build_request_and_score_agree(self):
        client = MagicMock()
        client.complete_json.return_value = (self._summary(), _llm_result())
        scorer = SurpriseScorer(client, use_rescue=False)
        transcript = _transcript()

        request = scorer.build_request(transcript, "CONSENSUS BLOCK", "Nvidia")
        scored = scorer.score(transcript, "CONSENSUS BLOCK", "Nvidia")

        self.assertEqual(request.custom_id, "NVDA_FY2025-Q1_surprise")
        self.assertEqual(scored.surprises[0].dimension, "demand")


class NoveltyScorerBatchSplitTests(unittest.TestCase):
    def _summary(self) -> TranscriptNoveltySummary:
        return TranscriptNoveltySummary(
            company_name="Nvidia",
            ticker="NVDA",
            fiscal_period="FY2025-Q1",
            novelties=[{"dimension": "management_confidence", "novelty_direction": "low_novelty", "novelty_magnitude": 0.0, "evidence": []}],
        )

    def test_build_request_and_score_agree(self):
        client = MagicMock()
        client.complete_json.return_value = (self._summary(), _llm_result())
        scorer = NoveltyScorer(client, use_rescue=False)
        transcript = _transcript()

        request = scorer.build_request(transcript, "PRIOR BLOCK", "Nvidia")
        scored = scorer.score(transcript, "PRIOR BLOCK", "Nvidia")

        self.assertEqual(request.custom_id, "NVDA_FY2025-Q1_novelty")
        self.assertEqual(scored.novelties[0].dimension, "management_confidence")


if __name__ == "__main__":
    unittest.main()
