"""Regression test for the prior-only-quarter view-write bug.

Scoring ONLY a prior-only quarter (no output-scope quarter in the same run)
used to leave `score_rows` empty and bail out *before* `dimension_view.json`
was written, even though the registry got marked done -- desyncing the
registry from the view. `finalize_and_write()` in run_dimension_scoring.py
must write the view whenever anything was scored, and skip only the CSV
write (to avoid clobbering existing output-scope history with an empty
frame) when there are zero output-scope rows.
"""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

import output_paths  # noqa: E402
import run_dimension_scoring as dim_mod  # noqa: E402
from company_config import CompanyProfile  # noqa: E402
from dimension_scorer import ScoredDimension, ScoredTranscript, TranscriptDimensionSummary  # noqa: E402
from transcript_providers import Transcript  # noqa: E402

sys.path.insert(0, str(ROOT))
from src.schemas.models import LLMResult, TokenUsage  # noqa: E402


def _transcript(ticker: str, fp: str) -> Transcript:
    return Transcript(
        ticker=ticker,
        fiscal_period=fp,
        call_date="2021-01-01",
        source_name="local",
        raw_text="Some transcript text.",
        prepared_remarks="Some transcript text.",
        qa_text="",
        speakers=["CEO"],
    )


def _scored(ticker: str, fp: str) -> ScoredTranscript:
    summary = TranscriptDimensionSummary(
        company_name="Test Co",
        ticker=ticker,
        fiscal_period=fp,
        dimensions=[{"dimension": "demand", "score": 1.0, "evidence": [], "rationale": "r"}],
    )
    dims = [
        ScoredDimension(
            dimension="demand", score=1.0, rationale="r", is_quant_comparable=True, evidence=[]
        )
    ]
    llm_result = LLMResult(usage=TokenUsage(input_tokens=1, output_tokens=1), raw_response="{}")
    return ScoredTranscript(summary=summary, dimensions=dims, llm_result=llm_result)


class PriorOnlyQuarterViewWriteTests(unittest.TestCase):
    def test_prior_only_only_run_still_writes_view(self):
        with TemporaryDirectory() as tmp, patch.object(output_paths, "ROOT", Path(tmp)):
            ticker = "TESTCO"
            fp = "FY2021-Q1"
            company = CompanyProfile(
                ticker=ticker,
                company_name="Test Co",
                output_quarters=(),
                prior_quarters=(fp,),
            )
            view_file = output_paths.company_artifact(ticker, "json", "dimension_view", "json", mkdir=True)
            audit_dir = output_paths.company_layer(ticker, "audit", mkdir=True)
            scope = dim_mod.DimensionScope(
                ticker=ticker,
                company=company,
                to_score=[fp],
                skipped=[],
                rerun_periods=None,
                extra_output=None,
                needs_merge=False,
                existing_view=None,
                view_file=view_file,
                scored_periods={fp},
                audit_dir=audit_dir,
                quant_dates={},
                quant_z={},
            )
            prepared = [{"fp": fp, "transcript": _transcript(ticker, fp)}]
            scored_by_fp = {fp: _scored(ticker, fp)}

            n_written = dim_mod.finalize_and_write(
                ticker, company, scope, prepared, [], scored_by_fp, "test-model"
            )

            self.assertEqual(n_written, 1)
            self.assertTrue(view_file.exists(), "dimension_view.json must be written for a prior-only-only run")
            view = json.loads(view_file.read_text(encoding="utf-8"))
            self.assertEqual(len(view["quarters"]), 1)
            self.assertEqual(view["quarters"][0]["fiscal_period"], fp)
            self.assertTrue(view["quarters"][0]["prior_only"])
            self.assertFalse(view["quarters"][0]["output_scope"])

            # No output-scope rows this run -> the CSV write must be skipped
            # rather than clobbering llm_dimension_scores.csv with an empty frame.
            csv_path = output_paths.company_artifact(ticker, "csv", "llm_dimension_scores", "csv")
            self.assertFalse(csv_path.exists())


class PromotePriorOnlyQuarterTests(unittest.TestCase):
    """A prior-only quarter later added to --extra-output-quarters has its
    dimensions skipped (already cached), so it never reaches the main
    scoring loop. finalize_and_write() must still flip its stale
    prior_only=true/output_scope=false view record and backfill its
    dimension-score CSV rows from the cached data -- no re-scoring needed.
    """

    def test_promoted_quarter_backfills_csv_rows_and_flips_flags(self):
        with TemporaryDirectory() as tmp, patch.object(output_paths, "ROOT", Path(tmp)):
            ticker = "TESTCO"
            fp = "FY2021-Q1"
            company = CompanyProfile(
                ticker=ticker,
                company_name="Test Co",
                output_quarters=(),
                prior_quarters=(),
            )
            view_file = output_paths.company_artifact(ticker, "json", "dimension_view", "json", mkdir=True)
            audit_dir = output_paths.company_layer(ticker, "audit", mkdir=True)
            existing_view = {
                "quarters": [
                    {
                        "fiscal_period": fp,
                        "output_scope": False,
                        "prior_only": True,
                        "as_of_date": "2021-01-01",
                        "source": "local",
                        "dimensions": [
                            {
                                "dimension": "demand",
                                "score": 1.0,
                                "is_quant_comparable": True,
                                "quant_z": None,
                                "rationale": "r",
                                "evidence": [
                                    {
                                        "claim": "c",
                                        "excerpt": "e",
                                        "verified": True,
                                        "status": "verbatim",
                                        "canonical": "e",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
            scope = dim_mod.DimensionScope(
                ticker=ticker,
                company=company,
                to_score=[],
                skipped=[fp],
                rerun_periods={fp},
                extra_output={fp},
                needs_merge=True,
                existing_view=existing_view,
                view_file=view_file,
                scored_periods=set(),
                audit_dir=audit_dir,
                quant_dates={},
                quant_z={},
            )

            n_written = dim_mod.finalize_and_write(ticker, company, scope, [], [], {}, "test-model")

            self.assertEqual(n_written, 1)
            view = json.loads(view_file.read_text(encoding="utf-8"))
            self.assertEqual(len(view["quarters"]), 1)
            self.assertFalse(view["quarters"][0]["prior_only"])
            self.assertTrue(view["quarters"][0]["output_scope"])

            csv_path = output_paths.company_artifact(ticker, "csv", "llm_dimension_scores", "csv")
            self.assertTrue(csv_path.exists(), "promoted quarter must backfill dimension-score CSV rows")


class ResolveScopePromotionTests(unittest.TestCase):
    """resolve_scope() must not silently return None (and only patch the
    top-level registry field) when a quarter needs *pure* promotion --
    already dims-scored, newly added to --extra-output-quarters, with
    nothing else needing fresh scoring. It should hand back a scope that
    routes through finalize_and_write()'s promotion patch instead.
    """

    def test_pure_promotion_returns_scope_not_none(self):
        with TemporaryDirectory() as tmp, patch.object(output_paths, "ROOT", Path(tmp)):
            ticker = "TESTCO"
            fp = "FY2021-Q1"
            company = CompanyProfile(
                ticker=ticker,
                company_name="Test Co",
                output_quarters=(),
                prior_quarters=(),
            )

            view_file = output_paths.company_artifact(ticker, "json", "dimension_view", "json", mkdir=True)
            view_file.write_text(
                json.dumps(
                    {
                        "quarters": [
                            {
                                "fiscal_period": fp,
                                "output_scope": False,
                                "prior_only": True,
                                "as_of_date": "2021-01-01",
                                "source": "local",
                                "dimensions": [
                                    {
                                        "dimension": "demand",
                                        "score": 1.0,
                                        "is_quant_comparable": True,
                                        "quant_z": None,
                                        "rationale": "r",
                                        "evidence": [
                                            {
                                                "claim": "c",
                                                "excerpt": "e",
                                                "verified": True,
                                                "status": "verbatim",
                                                "canonical": "e",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry_file = output_paths.company_artifact(ticker, "json", "quarter_registry", "json", mkdir=True)
            registry_file.write_text(
                json.dumps(
                    {
                        "ticker": ticker,
                        "scored_quarters": {
                            fp: {"dimensions_scored_at": "2021-01-01T00:00:00+00:00", "model": "m"}
                        },
                        "prior_only_quarters": [fp],
                    }
                ),
                encoding="utf-8",
            )

            args = argparse.Namespace(
                scope=None,
                quarters=[fp],
                extra_output_quarters=[fp],
                force=False,
            )
            with patch.object(dim_mod, "get_company", return_value=company):
                scope = dim_mod.resolve_scope(ticker, args)

            self.assertIsNotNone(scope, "a pure promotion must not resolve to None")
            self.assertEqual(scope.to_score, [])
            self.assertIn(fp, scope.skipped)
            self.assertTrue(scope.needs_merge)
            self.assertIsNotNone(scope.existing_view)

            n_written = dim_mod.finalize_and_write(ticker, company, scope, [], [], {}, "test-model")
            self.assertEqual(n_written, 1)
            view = json.loads(view_file.read_text(encoding="utf-8"))
            self.assertFalse(view["quarters"][0]["prior_only"])
            self.assertTrue(view["quarters"][0]["output_scope"])

    def test_no_promotable_quarter_still_returns_none(self):
        """Sanity check: when nothing is skipped-but-promotable (e.g. the
        quarter is already output scope), the old no-op None-return path
        still applies -- this must not regress into always returning a scope.
        """
        with TemporaryDirectory() as tmp, patch.object(output_paths, "ROOT", Path(tmp)):
            ticker = "TESTCO"
            fp = "FY2021-Q1"
            company = CompanyProfile(
                ticker=ticker,
                company_name="Test Co",
                output_quarters=(),
                prior_quarters=(),
            )

            view_file = output_paths.company_artifact(ticker, "json", "dimension_view", "json", mkdir=True)
            view_file.write_text(
                json.dumps(
                    {
                        "quarters": [
                            {
                                "fiscal_period": fp,
                                "output_scope": True,
                                "prior_only": False,
                                "dimensions": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry_file = output_paths.company_artifact(ticker, "json", "quarter_registry", "json", mkdir=True)
            registry_file.write_text(
                json.dumps(
                    {
                        "ticker": ticker,
                        "scored_quarters": {
                            fp: {"dimensions_scored_at": "2021-01-01T00:00:00+00:00", "model": "m"}
                        },
                        "prior_only_quarters": [],
                    }
                ),
                encoding="utf-8",
            )

            args = argparse.Namespace(
                scope=None,
                quarters=[fp],
                extra_output_quarters=[fp],
                force=False,
            )
            with patch.object(dim_mod, "get_company", return_value=company):
                scope = dim_mod.resolve_scope(ticker, args)

            self.assertIsNone(scope, "already-promoted quarter has nothing left to do")


if __name__ == "__main__":
    unittest.main()
