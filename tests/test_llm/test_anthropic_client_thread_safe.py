import threading
import unittest
from unittest.mock import MagicMock, patch

from src.llm.anthropic_client import AnthropicClient
from src.schemas.models import LLMResult, TokenUsage
from pydantic import BaseModel


class _SampleResponse(BaseModel):
    value: str = "ok"


class AnthropicClientThreadSafeTestCase(unittest.TestCase):
    @patch("src.llm.anthropic_client.anthropic.Anthropic")
    def test_parallel_calls_aggregate_token_usage(self, mock_anthropic_cls):
        client = AnthropicClient(api_key="test-key", model="claude-test")

        def make_response(input_tokens: int, output_tokens: int):
            response = MagicMock()
            response.content = [MagicMock(type="text", text='{"value":"ok"}')]
            response.usage.input_tokens = input_tokens
            response.usage.output_tokens = output_tokens
            return response

        mock_anthropic_cls.return_value.messages.create.side_effect = [
            make_response(10, 5),
            make_response(20, 8),
            make_response(15, 7),
        ]

        errors: list[Exception] = []

        def worker():
            try:
                client.complete_json(
                    system_prompt="test",
                    user_content="hello",
                    response_model=_SampleResponse,
                    label="worker",
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(client.total_input_tokens, 45)
        self.assertEqual(client.total_output_tokens, 20)


if __name__ == "__main__":
    unittest.main()
