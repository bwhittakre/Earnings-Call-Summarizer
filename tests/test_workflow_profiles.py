"""Focused tests for callable Structured Narrative workflow profiles."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

from workflow_profiles import (  # noqa: E402
    WorkflowProfile,
    execute_plan,
    plan_workflow,
)
from export_inbox_to_transcripts_raw import fiscal_period_from_filename  # noqa: E402
import run_company_pipeline  # noqa: E402


class WorkflowProfilePlanningTests(unittest.TestCase):
    def plan(self, profile: WorkflowProfile, **kwargs):
        return plan_workflow(
            profile,
            ticker="msft",
            quarter="fy2026-q1",
            python_executable="python",
            structured_narrative_dir=Path("SN"),
            **kwargs,
        )

    def test_inbox_bridge_accepts_monitor_underscore_filename(self):
        self.assertEqual(
            fiscal_period_from_filename(Path("AAPL_FY2026_Q2.txt")),
            ("AAPL", "FY2026-Q2"),
        )

    def test_pre_release_scores_prior_quarter_as_dimensions_only_baseline(self):
        plan = self.plan(WorkflowProfile.PRE_RELEASE, force=True)

        self.assertEqual(plan.ticker, "MSFT")
        self.assertEqual(plan.quarter, "FY2026-Q1")
        self.assertEqual(len(plan.commands), 1)
        argv = plan.commands[0].argv
        self.assertEqual(argv[argv.index("--baseline-quarter") + 1], "FY2025-Q4")
        self.assertIn("--force", argv)
        self.assertNotIn("--append-quarters", argv)
        self.assertNotIn("--extra-output-quarters", argv)

    def test_pre_release_no_prior_returns_empty_successful_plan(self):
        plan = self.plan(WorkflowProfile.PRE_RELEASE, no_prior=True)

        self.assertEqual(plan.commands, ())
        self.assertEqual(plan.ticker, "MSFT")
        self.assertEqual(plan.quarter, "FY2026-Q1")

    def test_release_to_call_prepares_quant_without_transcript_scoring(self):
        plan = self.plan(WorkflowProfile.RELEASE_TO_CALL)

        self.assertEqual(len(plan.commands), 1)
        argv = plan.commands[0].argv
        self.assertIn("--quant-only", argv)
        self.assertNotIn("--skip-quant", argv)
        self.assertNotIn("--new-quarter", argv)
        self.assertEqual(argv[argv.index("--append-quarters") + 1], "FY2026-Q1")
        self.assertNotIn("export_inbox_to_transcripts_raw.py", " ".join(argv))

    def test_post_call_reuses_quant_and_bridges_once(self):
        plan = self.plan(
            WorkflowProfile.POST_CALL,
            force=True,
            spine_tickers=("msft", "aapl"),
        )

        self.assertEqual(len(plan.commands), 3)
        self.assertIn("export_inbox_to_transcripts_raw.py", plan.commands[0].argv[1])
        score_argv = plan.commands[1].argv
        self.assertIn("--skip-quant", score_argv)
        self.assertIn("--skip-bridge", score_argv)
        self.assertIn("--force", score_argv)
        self.assertNotIn("--append-quarters", score_argv)
        self.assertEqual(score_argv[score_argv.index("--new-quarter") + 1], "FY2026-Q1")
        self.assertEqual(plan.commands[2].argv[-2:], ("MSFT", "AAPL"))
        self.assertNotIn("--include-labels", plan.commands[2].argv)

    def test_post_call_research_mode_opts_into_forward_labels(self):
        plan = self.plan(
            WorkflowProfile.POST_CALL,
            bridge_transcript=False,
            spine_tickers=("msft",),
            research_labels=True,
        )

        self.assertEqual(len(plan.commands), 3)
        self.assertIn("--include-labels", plan.commands[1].argv)
        self.assertIn("evaluate_narrative_signals.py", plan.commands[2].argv[1])

    def test_post_call_can_skip_bridge_and_cross_company_exports(self):
        plan = self.plan(
            WorkflowProfile.POST_CALL,
            bridge_transcript=False,
            export_spine=False,
        )

        self.assertEqual(len(plan.commands), 1)
        self.assertIn("--skip-quant", plan.commands[0].argv)
        self.assertIn("--skip-bridge", plan.commands[0].argv)

    def test_post_call_no_prior_passes_flag_to_pipeline(self):
        plan = self.plan(
            WorkflowProfile.POST_CALL,
            bridge_transcript=False,
            export_spine=False,
            no_prior=True,
        )

        self.assertEqual(len(plan.commands), 1)
        self.assertIn("--no-prior", plan.commands[0].argv)

    def test_execute_plan_uses_injected_runner_in_order(self):
        plan = self.plan(
            WorkflowProfile.POST_CALL,
            bridge_transcript=False,
            export_spine=False,
        )
        seen = []

        execute_plan(plan, runner=seen.append)

        self.assertEqual(seen, list(plan.commands))

    def test_pipeline_baseline_dispatches_only_dimension_scoring(self):
        argv = [
            "run_company_pipeline.py",
            "--ticker",
            "msft",
            "--baseline-quarter",
            "fy2025-q4",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(run_company_pipeline, "run_step") as run_step,
            patch.object(run_company_pipeline, "ensure_company_tree"),
            patch.object(run_company_pipeline, "is_pit_mode", return_value=False),
        ):
            result = run_company_pipeline.main()

        self.assertEqual(result, 0)
        run_step.assert_called_once()
        command = run_step.call_args.args[1]
        self.assertIn("run_dimension_scoring.py", command[1])
        self.assertEqual(command[command.index("--quarters") + 1], "FY2025-Q4")
        self.assertNotIn("--extra-output-quarters", command)

    def test_pipeline_quant_only_stops_before_panel_and_validation(self):
        argv = [
            "run_company_pipeline.py",
            "--ticker",
            "msft",
            "--quant-only",
            "--append-quarters",
            "fy2026-q1",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(run_company_pipeline, "run_step") as run_step,
            patch.object(run_company_pipeline, "ensure_company_tree"),
            patch.object(run_company_pipeline, "is_pit_mode", return_value=False),
            patch.object(
                run_company_pipeline,
                "resolve_read_parquet_or_csv",
                return_value=None,
            ),
        ):
            result = run_company_pipeline.main()

        self.assertEqual(result, 0)
        labels = [call.args[0] for call in run_step.call_args_list]
        self.assertEqual(labels, ["Quant extract", "Quant z-score", "Feature panel"])
        self.assertNotIn("Join validation", labels)
        self.assertNotIn("Panel quant validation", labels)
        extract_command = run_step.call_args_list[0].args[1]
        self.assertEqual(
            extract_command[extract_command.index("--append-quarters") + 1],
            "fy2026-q1",
        )
        panel_command = run_step.call_args_list[2].args[1]
        self.assertIn("build_feature_panel.py", panel_command[1])
        self.assertIn("--from-registry", panel_command)
        self.assertEqual(
            panel_command[panel_command.index("--include-quarters") + 1],
            "FY2026-Q1",
        )

    def test_resolve_new_quarter_args_no_prior_does_not_prepend(self):
        with (
            patch.object(
                run_company_pipeline,
                "ensure_registry",
                return_value={"scored_quarters": {}},
            ),
            patch.object(run_company_pipeline, "is_quarter_complete", return_value=False),
        ):
            with_prior = run_company_pipeline.resolve_new_quarter_args(
                "SPCX", "FY2026-Q2", force=False
            )
            without_prior = run_company_pipeline.resolve_new_quarter_args(
                "SPCX", "FY2026-Q2", force=False, no_prior=True
            )

        self.assertEqual(with_prior, ["--quarters", "FY2026-Q1", "FY2026-Q2"])
        self.assertEqual(without_prior, ["--quarters", "FY2026-Q2"])


if __name__ == "__main__":
    unittest.main()
