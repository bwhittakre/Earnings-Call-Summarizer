"""Tests for the shared batch-orchestration helper (Structured Narrative/batch_scoring.py)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

from batch_scoring import run_batch  # noqa: E402

from src.llm.anthropic_client import BatchItemResult, BatchRequestItem  # noqa: E402
from src.schemas.models import TokenUsage  # noqa: E402


class _DummyModel(BaseModel):
    value: str


class _OtherModel(BaseModel):
    other: str


def _client_with_statuses(statuses: list[str]):
    client = MagicMock()
    client.submit_batch.return_value = "batch_123"
    client.get_batch.side_effect = [MagicMock(processing_status=s, request_counts=None) for s in statuses]
    return client


class RunBatchTests(unittest.TestCase):
    def test_empty_items_returns_empty_without_submitting(self):
        client = MagicMock()
        outcomes = run_batch(client, [], _DummyModel)
        self.assertEqual(outcomes, {})
        client.submit_batch.assert_not_called()

    def test_submits_polls_until_ended_and_parses_succeeded_results(self):
        client = _client_with_statuses(["in_progress", "in_progress", "ended"])
        client.retrieve_batch_results.return_value = [
            BatchItemResult(
                custom_id="a",
                raw_text='{"value": "ok"}',
                usage=TokenUsage(input_tokens=10, output_tokens=5),
                error=None,
            ),
        ]
        client.parse_batch_result.return_value = _DummyModel(value="ok")

        sleeps: list[float] = []
        items = [BatchRequestItem(custom_id="a", system_prompt="SYS", user_content="U")]

        outcomes = run_batch(client, items, _DummyModel, poll_interval=5.0, sleep_fn=sleeps.append)

        client.submit_batch.assert_called_once_with(items)
        self.assertEqual(client.get_batch.call_count, 3)
        self.assertEqual(sleeps, [5.0, 5.0])  # slept between the two non-ended polls
        self.assertIn("a", outcomes)
        self.assertTrue(outcomes["a"].ok)
        self.assertEqual(outcomes["a"].parsed.value, "ok")

    def test_errored_item_reports_error_without_raising(self):
        client = _client_with_statuses(["ended"])
        client.retrieve_batch_results.return_value = [
            BatchItemResult(custom_id="b", raw_text=None, usage=None, error="errored: boom"),
        ]
        items = [BatchRequestItem(custom_id="b", system_prompt="SYS", user_content="U")]

        outcomes = run_batch(client, items, _DummyModel, sleep_fn=lambda _: None)

        self.assertFalse(outcomes["b"].ok)
        self.assertEqual(outcomes["b"].error, "errored: boom")
        client.parse_batch_result.assert_not_called()

    def test_succeeded_result_missing_usage_is_treated_as_error(self):
        """Defensive: a "succeeded" item (error=None) should always carry usage
        in practice (AnthropicClient.retrieve_batch_results guarantees this),
        but run_batch must not crash constructing LLMResult if it doesn't."""
        client = _client_with_statuses(["ended"])
        client.retrieve_batch_results.return_value = [
            BatchItemResult(custom_id="d", raw_text='{"value": "ok"}', usage=None, error=None),
        ]
        items = [BatchRequestItem(custom_id="d", system_prompt="SYS", user_content="U")]

        outcomes = run_batch(client, items, _DummyModel, sleep_fn=lambda _: None)

        self.assertFalse(outcomes["d"].ok)
        client.parse_batch_result.assert_not_called()

    def test_parse_failure_reports_error_without_raising(self):
        client = _client_with_statuses(["ended"])
        client.retrieve_batch_results.return_value = [
            BatchItemResult(
                custom_id="c",
                raw_text="not json",
                usage=TokenUsage(input_tokens=10, output_tokens=5),
                error=None,
            ),
        ]
        client.parse_batch_result.side_effect = ValueError("bad json")
        items = [BatchRequestItem(custom_id="c", system_prompt="SYS", user_content="U")]

        outcomes = run_batch(client, items, _DummyModel, sleep_fn=lambda _: None)

        self.assertFalse(outcomes["c"].ok)
        self.assertIn("bad json", outcomes["c"].error)

    def test_mixed_response_model_dict_routes_each_item_to_its_own_model(self):
        """run_universe_batch.py combines items from different scoring stages
        (each with its own Pydantic response model) into one batch — verify
        run_batch() parses each result with the model keyed by its custom_id,
        not a single uniform model."""
        client = _client_with_statuses(["ended"])
        client.retrieve_batch_results.return_value = [
            BatchItemResult(
                custom_id="a",
                raw_text='{"value": "ok"}',
                usage=TokenUsage(input_tokens=10, output_tokens=5),
                error=None,
            ),
            BatchItemResult(
                custom_id="b",
                raw_text='{"other": "ok2"}',
                usage=TokenUsage(input_tokens=8, output_tokens=4),
                error=None,
            ),
        ]

        def _parse(item_result, model):
            return model(**{list(model.model_fields)[0]: "ok" if item_result.custom_id == "a" else "ok2"})

        client.parse_batch_result.side_effect = _parse
        items = [
            BatchRequestItem(custom_id="a", system_prompt="SYS", user_content="U"),
            BatchRequestItem(custom_id="b", system_prompt="SYS", user_content="U"),
        ]

        outcomes = run_batch(
            client, items, {"a": _DummyModel, "b": _OtherModel}, sleep_fn=lambda _: None
        )

        self.assertIsInstance(outcomes["a"].parsed, _DummyModel)
        self.assertIsInstance(outcomes["b"].parsed, _OtherModel)
        self.assertEqual(outcomes["a"].parsed.value, "ok")
        self.assertEqual(outcomes["b"].parsed.other, "ok2")

    def test_timeout_raises_when_batch_never_ends(self):
        client = MagicMock()
        client.submit_batch.return_value = "batch_123"
        client.get_batch.return_value = MagicMock(processing_status="in_progress", request_counts=None)
        items = [BatchRequestItem(custom_id="a", system_prompt="SYS", user_content="U")]

        # A negative timeout is exceeded on the very first status check (elapsed
        # time since start is always >= 0), so this raises without ever sleeping.
        with self.assertRaises(TimeoutError):
            run_batch(client, items, _DummyModel, timeout=-1, sleep_fn=lambda _: None)


if __name__ == "__main__":
    unittest.main()
