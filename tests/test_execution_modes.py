from __future__ import annotations

import argparse
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

from batch_scoring import (  # noqa: E402
    add_execution_mode_arguments,
    print_usage_report,
    requested_quarter_count,
    resolve_execution_mode,
)


class ExecutionModeResolverTests(unittest.TestCase):
    def test_auto_single_ticker_quarter_is_sync(self):
        result = resolve_execution_mode("auto", ticker_count=1, quarter_count=1)
        self.assertEqual(result.resolved_mode, "sync")
        self.assertEqual(result.item_count, 1)

    def test_auto_uses_requested_cardinality_not_remaining_work(self):
        result = resolve_execution_mode("auto", ticker_count=1, quarter_count=8)
        self.assertEqual(result.resolved_mode, "batch")

    def test_auto_multiple_tickers_is_batch(self):
        result = resolve_execution_mode(None, ticker_count=2, quarter_count=1)
        self.assertEqual(result.resolved_mode, "batch")

    def test_explicit_batch_overrides_small_job(self):
        result = resolve_execution_mode("batch", ticker_count=1, quarter_count=1)
        self.assertEqual(result.resolved_mode, "batch")

    def test_oversized_sync_requires_confirmation(self):
        with self.assertRaisesRegex(ValueError, "confirm-expensive-sync"):
            resolve_execution_mode("sync", ticker_count=1, quarter_count=2)
        result = resolve_execution_mode(
            "sync", ticker_count=1, quarter_count=2, confirm_expensive_sync=True
        )
        self.assertEqual(result.resolved_mode, "sync")

    def test_batch_alias_is_compatible_and_conflicts_cleanly(self):
        self.assertEqual(
            resolve_execution_mode(
                None, ticker_count=1, quarter_count=1, batch_alias=True
            ).resolved_mode,
            "batch",
        )
        self.assertEqual(
            resolve_execution_mode(
                "batch", ticker_count=1, quarter_count=1, batch_alias=True
            ).resolved_mode,
            "batch",
        )
        with self.assertRaisesRegex(ValueError, "conflicts"):
            resolve_execution_mode(
                "sync", ticker_count=1, quarter_count=1, batch_alias=True
            )

    def test_cli_alias_parses_and_conflicting_mode_is_rejected(self):
        parser = argparse.ArgumentParser()
        add_execution_mode_arguments(parser)
        alias_args = parser.parse_args(["--batch"])
        self.assertTrue(alias_args.batch)
        self.assertEqual(
            resolve_execution_mode(
                alias_args.execution_mode,
                ticker_count=1,
                quarter_count=1,
                batch_alias=alias_args.batch,
            ).resolved_mode,
            "batch",
        )
        conflict = parser.parse_args(["--batch", "--execution-mode", "sync"])
        with self.assertRaisesRegex(ValueError, "conflicts"):
            resolve_execution_mode(
                conflict.execution_mode,
                ticker_count=1,
                quarter_count=1,
                batch_alias=conflict.batch,
            )

    def test_unqualified_and_scope_requests_are_conservatively_historical(self):
        self.assertEqual(requested_quarter_count(SimpleNamespace(quarters=[])), 2)
        self.assertEqual(
            requested_quarter_count(
                SimpleNamespace(quarters=[], new_quarter="FY2026-Q1")
            ),
            1,
        )


class WorkflowModeTests(unittest.TestCase):
    def test_historical_wrappers_explicitly_request_batch(self):
        for name in (
            "_run_historical_backfill.py",
            "run_fill_gaps_batch.py",
            "run_pilot_8q_batch.py",
        ):
            source = (SN / name).read_text(encoding="utf-8")
            self.assertIn('"--execution-mode"', source, name)
            self.assertIn('"batch"', source, name)


class ReportingTests(unittest.TestCase):
    def test_known_model_reports_sync_and_batch_cost(self):
        client = SimpleNamespace(
            model="claude-sonnet-4-6",
            total_input_tokens=1_000_000,
            total_output_tokens=100_000,
            total_cache_creation_tokens=10_000,
            total_cache_read_tokens=20_000,
            usage_summary=lambda: "usage",
        )
        sync_output = io.StringIO()
        with redirect_stdout(sync_output):
            print_usage_report(client, "sync", 1.0)
        self.assertIn("Estimated API cost: $4.5435 USD", sync_output.getvalue())
        self.assertIn("synchronous standard pricing", sync_output.getvalue())

        batch_output = io.StringIO()
        with redirect_stdout(batch_output):
            print_usage_report(client, "batch", 1.0)
        self.assertIn("Estimated API cost: $2.2717 USD", batch_output.getvalue())
        self.assertIn("Batch API discount applies", batch_output.getvalue())

    def test_unknown_model_reports_tokens_and_unavailable_cost(self):
        client = SimpleNamespace(
            model="test-model",
            usage_summary=lambda: (
                "Total tokens — input: 10, output: 5, total: 15 | "
                "cache — write: 2, read: 3"
            ),
        )
        output = io.StringIO()
        with redirect_stdout(output):
            print_usage_report(client, "batch", 1.25)
        text = output.getvalue()
        self.assertIn("input: 10", text)
        self.assertIn("Elapsed: 1.25s", text)
        self.assertIn("Estimated API cost: unavailable", text)
        self.assertIn("Batch API discount applies", text)


if __name__ == "__main__":
    unittest.main()
