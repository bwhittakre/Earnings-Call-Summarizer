"""Tests for run_universe_batch.py's routing logic.

These mock resolve_scope/prepare_items/finalize_and_write (and run_batch
itself) so the tests exercise ONLY the orchestrator's own job: combining
items from multiple tickers (and, for the combined group, multiple stages)
into a single run_batch() call, then routing each outcome back to the
correct ticker/stage's finalize_and_write() -- including the synchronous
retry path for items a batch reports as failed.
"""
from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

import run_universe_batch as ub  # noqa: E402
from batch_scoring import BatchOutcome  # noqa: E402


def _args(**overrides) -> argparse.Namespace:
    base = {"batch_poll_interval": 1.0, "batch_timeout": None}
    base.update(overrides)
    return argparse.Namespace(**base)


class DimensionsGroupRoutingTests(unittest.TestCase):
    def test_combines_all_tickers_into_one_batch_and_routes_results(self):
        """AMZN's item succeeds in the batch; MSFT's item is reported failed
        and must fall back to a synchronous scorer.score() retry -- both
        outcomes must reach finalize_and_write() for the RIGHT ticker."""
        fake_scorer = MagicMock()
        fake_scorer.RESPONSE_MODEL = MagicMock(name="DimensionResponseModel")
        fake_scorer.build_request.side_effect = (
            lambda transcript, company_name: MagicMock(custom_id=f"{transcript.ticker}_dim")
        )
        fake_scorer.finalize.side_effect = (
            lambda parsed, llm_result, custom_id, text: f"finalized-{custom_id}"
        )
        fake_scorer.score.side_effect = lambda transcript, company_name: f"sync-{transcript.ticker}"

        def fake_resolve_scope(ticker, args):
            scope = MagicMock()
            scope.company = MagicMock(company_name=f"{ticker} Inc")
            return scope

        def fake_prepare_items(scope, provider):
            transcript = MagicMock()
            transcript.ticker = scope.company.company_name.split()[0]
            return [{"fp": "FY2025-Q1", "transcript": transcript}], []

        finalize_calls: list[tuple[str, dict]] = []

        def fake_finalize_and_write(ticker, company, scope, prepared, failed_coverage, scored_by_fp, model):
            finalize_calls.append((ticker, dict(scored_by_fp)))
            return len(scored_by_fp)

        def fake_run_batch(client, items, response_model, poll_interval=None, timeout=None):
            outcomes = {}
            for item in items:
                if "AMZN" in item.custom_id:
                    outcomes[item.custom_id] = BatchOutcome(
                        custom_id=item.custom_id, parsed="P", llm_result=MagicMock(), error=None
                    )
                else:
                    outcomes[item.custom_id] = BatchOutcome(
                        custom_id=item.custom_id, parsed=None, llm_result=None, error="boom"
                    )
            return outcomes

        with patch.object(ub.dim_mod, "DimensionScorer", return_value=fake_scorer), \
             patch.object(ub.dim_mod, "resolve_scope", side_effect=fake_resolve_scope), \
             patch.object(ub.dim_mod, "prepare_items", side_effect=fake_prepare_items), \
             patch.object(ub.dim_mod, "finalize_and_write", side_effect=fake_finalize_and_write), \
             patch.object(ub, "run_batch", side_effect=fake_run_batch) as mock_run_batch:
            written = ub._run_dimensions_group(
                ["AMZN", "MSFT"],
                {"AMZN": argparse.Namespace(), "MSFT": argparse.Namespace()},
                client=MagicMock(),
                use_rescue=False,
                provider=MagicMock(),
                model="test-model",
                args=_args(),
            )

        mock_run_batch.assert_called_once()
        _, called_items = mock_run_batch.call_args[0][:2]
        self.assertEqual(len(called_items), 2)  # one batch call, both tickers combined

        self.assertEqual(written, {"AMZN": 1, "MSFT": 1})
        calls_by_ticker = dict(finalize_calls)
        self.assertEqual(calls_by_ticker["AMZN"]["FY2025-Q1"], "finalized-AMZN_dim")
        self.assertEqual(calls_by_ticker["MSFT"]["FY2025-Q1"], "sync-MSFT")


class CombinedGroupRoutingTests(unittest.TestCase):
    def test_routes_outcomes_to_correct_stage_and_ticker(self):
        """delta+surprise items for AMZN+MSFT go into ONE run_batch() call;
        AMZN's items succeed, MSFT's are reported failed and retried
        synchronously -- each outcome must land on the right (stage, ticker)."""
        calls: list[tuple[str, str, dict]] = []

        def make_adapter(stage: str) -> "ub._StageAdapter":
            def resolve_scope(ticker, args):
                scope = MagicMock()
                scope.ticker = ticker
                scope.company = MagicMock(company_name=f"{ticker} Inc")
                return scope

            def prepare_items(scope, provider):
                return [{"transcript": MagicMock(raw_text="TXT"), "key": "only", "ticker": scope.ticker}]

            def build_item(scorer, company, p):
                return MagicMock(custom_id=f"{stage}_{p['ticker']}")

            def sync_score(scorer, company, p):
                return f"sync-{stage}-{p['ticker']}"

            def finalize_and_write(ticker, company, scope, prepared, scored_by_key, model):
                calls.append((stage, ticker, dict(scored_by_key)))
                return len(scored_by_key)

            return ub._StageAdapter(
                resolve_scope=resolve_scope,
                prepare_items=prepare_items,
                finalize_and_write=finalize_and_write,
                response_model=MagicMock(name=f"{stage}-model"),
                build_item=build_item,
                sync_score=sync_score,
                key_of=lambda p: p["key"],
            )

        fake_scorer = MagicMock()
        fake_scorer.finalize.side_effect = (
            lambda parsed, llm_result, custom_id, text: f"finalized-{custom_id}"
        )

        def fake_run_batch(client, items, response_models, poll_interval=None, timeout=None):
            outcomes = {}
            for item in items:
                if "AMZN" in item.custom_id:
                    outcomes[item.custom_id] = BatchOutcome(
                        custom_id=item.custom_id, parsed="P", llm_result=MagicMock(), error=None
                    )
                else:
                    outcomes[item.custom_id] = BatchOutcome(
                        custom_id=item.custom_id, parsed=None, llm_result=None, error="boom"
                    )
            return outcomes

        fake_adapters = {"delta": make_adapter("delta"), "surprise": make_adapter("surprise")}
        with patch.dict(ub._COMBINED_ADAPTERS, fake_adapters, clear=True), \
             patch.object(ub, "_make_combined_scorer", return_value=fake_scorer), \
             patch.object(ub, "run_batch", side_effect=fake_run_batch) as mock_run_batch:
            written = ub._run_combined_group(
                ["delta", "surprise"],
                ["AMZN", "MSFT"],
                {"AMZN": argparse.Namespace(), "MSFT": argparse.Namespace()},
                client=MagicMock(),
                use_rescue=False,
                delta_context="summary",
                provider=MagicMock(),
                model="test-model",
                args=_args(),
            )

        mock_run_batch.assert_called_once()
        _, called_items = mock_run_batch.call_args[0][:2]
        self.assertEqual(len(called_items), 4)  # 2 stages x 2 tickers, one combined batch

        self.assertEqual(written, {"AMZN": {"delta": 1, "surprise": 1}, "MSFT": {"delta": 1, "surprise": 1}})
        calls_by_key = {(stage, ticker): scored for stage, ticker, scored in calls}
        self.assertEqual(calls_by_key[("delta", "AMZN")]["only"], "finalized-delta_AMZN")
        self.assertEqual(calls_by_key[("surprise", "AMZN")]["only"], "finalized-surprise_AMZN")
        self.assertEqual(calls_by_key[("delta", "MSFT")]["only"], "sync-delta-MSFT")
        self.assertEqual(calls_by_key[("surprise", "MSFT")]["only"], "sync-surprise-MSFT")


if __name__ == "__main__":
    unittest.main()
