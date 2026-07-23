import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from pydantic import BaseModel

from src.llm.anthropic_client import AnthropicClient, BatchItemResult, BatchRequestItem


class _DummyModel(BaseModel):
    value: str


def _content_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _usage(input_tokens=100, output_tokens=20, cache_creation=None, cache_read=None):
    """A plain namespace usage object; cache_* fields are only set when passed,
    so tests can simulate provider responses that predate prompt caching."""
    kwargs = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    if cache_creation is not None:
        kwargs["cache_creation_input_tokens"] = cache_creation
    if cache_read is not None:
        kwargs["cache_read_input_tokens"] = cache_read
    return SimpleNamespace(**kwargs)


def _response(text, usage):
    return SimpleNamespace(content=[_content_block(text)], usage=usage)


def _client() -> AnthropicClient:
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-4-6", max_retries=1)
    client.client = MagicMock()
    return client


class CompleteJsonCachingTests(unittest.TestCase):
    def test_system_prompt_sent_as_cacheable_block(self):
        client = _client()
        client.client.messages.create.return_value = _response(
            '{"value": "ok"}', _usage()
        )

        client.complete_json(
            system_prompt="SYSTEM PROMPT TEXT",
            user_content="USER CONTENT",
            response_model=_DummyModel,
            label="test_label",
        )

        _, kwargs = client.client.messages.create.call_args
        self.assertEqual(
            kwargs["system"],
            [
                {
                    "type": "text",
                    "text": "SYSTEM PROMPT TEXT",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        )

    def test_cache_token_fields_populated_from_response(self):
        client = _client()
        client.client.messages.create.return_value = _response(
            '{"value": "ok"}',
            _usage(cache_creation=900, cache_read=0),
        )

        _, result = client.complete_json(
            system_prompt="SYSTEM",
            user_content="USER",
            response_model=_DummyModel,
            label="test_label",
        )
        self.assertEqual(result.usage.cache_creation_input_tokens, 900)
        self.assertEqual(result.usage.cache_read_input_tokens, 0)
        self.assertEqual(client.total_cache_creation_tokens, 900)
        self.assertEqual(client.total_cache_read_tokens, 0)

    def test_cache_read_hit_accumulates_across_calls(self):
        client = _client()
        client.client.messages.create.side_effect = [
            _response('{"value": "a"}', _usage(cache_creation=900, cache_read=0)),
            _response('{"value": "b"}', _usage(cache_creation=0, cache_read=900)),
        ]

        client.complete_json("SYSTEM", "USER1", _DummyModel, "call_1")
        client.complete_json("SYSTEM", "USER2", _DummyModel, "call_2")

        self.assertEqual(client.total_cache_creation_tokens, 900)
        self.assertEqual(client.total_cache_read_tokens, 900)
        self.assertEqual(client.total_input_tokens, 200)  # 100 + 100

    def test_missing_cache_fields_default_to_zero(self):
        """Older/degraded provider responses without cache_* attrs shouldn't crash."""
        client = _client()
        client.client.messages.create.return_value = _response(
            '{"value": "ok"}', _usage()  # no cache_creation/cache_read kwargs set
        )

        _, result = client.complete_json("SYSTEM", "USER", _DummyModel, "label")
        self.assertEqual(result.usage.cache_creation_input_tokens, 0)
        self.assertEqual(result.usage.cache_read_input_tokens, 0)

    def test_usage_summary_reports_cache_totals(self):
        client = _client()
        client.client.messages.create.return_value = _response(
            '{"value": "ok"}', _usage(cache_creation=900, cache_read=0)
        )
        client.complete_json("SYSTEM", "USER", _DummyModel, "label")
        summary = client.usage_summary()
        self.assertIn("cache", summary)
        self.assertIn("900", summary)


class BatchApiTests(unittest.TestCase):
    def test_submit_batch_sends_cacheable_system_and_custom_ids(self):
        client = _client()
        client.client.messages.batches.create.return_value = SimpleNamespace(id="batch_123")

        items = [
            BatchRequestItem(custom_id="AAPL_FY2024-Q1_dimensions", system_prompt="SYS", user_content="U1"),
            BatchRequestItem(custom_id="AAPL_FY2024-Q2_dimensions", system_prompt="SYS", user_content="U2"),
        ]
        batch_id = client.submit_batch(items)

        self.assertEqual(batch_id, "batch_123")
        _, kwargs = client.client.messages.batches.create.call_args
        requests = kwargs["requests"]
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["custom_id"], "AAPL_FY2024-Q1_dimensions")
        self.assertEqual(
            requests[0]["params"]["system"],
            [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}],
        )
        self.assertEqual(requests[1]["custom_id"], "AAPL_FY2024-Q2_dimensions")

    def test_get_batch_returns_raw_batch_object(self):
        client = _client()
        client.client.messages.batches.retrieve.return_value = SimpleNamespace(
            id="batch_123", processing_status="in_progress"
        )
        batch = client.get_batch("batch_123")
        self.assertEqual(batch.processing_status, "in_progress")
        client.client.messages.batches.retrieve.assert_called_once_with("batch_123")

    def test_retrieve_batch_results_parses_succeeded_items_and_accumulates_usage(self):
        client = _client()
        succeeded_entry = SimpleNamespace(
            custom_id="AAPL_FY2024-Q1_dimensions",
            result=SimpleNamespace(
                type="succeeded",
                message=SimpleNamespace(
                    content=[_content_block('{"value": "ok"}')],
                    usage=_usage(cache_creation=0, cache_read=900),
                ),
            ),
        )
        client.client.messages.batches.results.return_value = [succeeded_entry]

        results = client.retrieve_batch_results("batch_123")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].custom_id, "AAPL_FY2024-Q1_dimensions")
        self.assertIsNone(results[0].error)
        self.assertEqual(results[0].raw_text, '{"value": "ok"}')
        self.assertEqual(results[0].usage.cache_read_input_tokens, 900)
        self.assertEqual(client.total_cache_read_tokens, 900)

    def test_retrieve_batch_results_marks_errored_items(self):
        client = _client()
        errored_entry = SimpleNamespace(
            custom_id="AAPL_FY2024-Q2_dimensions",
            result=SimpleNamespace(type="errored", error=SimpleNamespace(message="boom")),
        )
        client.client.messages.batches.results.return_value = [errored_entry]

        results = client.retrieve_batch_results("batch_123")

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].raw_text)
        self.assertIsNone(results[0].usage)
        self.assertIn("errored", results[0].error)

    def test_parse_batch_result_parses_succeeded_result(self):
        client = _client()
        result = BatchItemResult(
            custom_id="AAPL_FY2024-Q1_dimensions",
            raw_text='{"value": "ok"}',
            usage=None,
            error=None,
        )
        parsed = client.parse_batch_result(result, _DummyModel)
        self.assertEqual(parsed.value, "ok")

    def test_parse_batch_result_raises_for_errored_item(self):
        client = _client()
        result = BatchItemResult(
            custom_id="AAPL_FY2024-Q2_dimensions",
            raw_text=None,
            usage=None,
            error="errored: boom",
        )
        with self.assertRaises(ValueError):
            client.parse_batch_result(result, _DummyModel)

    def test_parse_batch_result_raises_and_saves_artifact_on_bad_json(self):
        client = _client()
        result = BatchItemResult(
            custom_id="AAPL_FY2024-Q3_dimensions",
            raw_text="not json at all",
            usage=None,
            error=None,
        )
        with self.assertRaises(ValueError):
            client.parse_batch_result(result, _DummyModel)


if __name__ == "__main__":
    unittest.main()
