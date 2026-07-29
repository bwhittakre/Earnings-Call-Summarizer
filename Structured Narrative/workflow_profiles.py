#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Callable command plans for the event-time Structured Narrative workflow.

The plans intentionally compose the existing command-line entry points instead
of importing their implementation details.  This keeps fiscal normalization,
PIT configuration, registry handling, and subprocess isolation in the scripts
that already own those concerns while giving services an inspectable,
unit-testable interface.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from company_config import PILOT_TICKERS  # noqa: E402
from fiscal_period_util import normalize_fiscal_period, prior_fiscal_period  # noqa: E402


class WorkflowProfile(str, Enum):
    """Supported event-time service workflows."""

    PRE_RELEASE = "pre_release"
    RELEASE_TO_CALL = "release_to_call"
    POST_CALL = "post_call"


@dataclass(frozen=True)
class WorkflowCommand:
    """One subprocess invocation in a workflow plan."""

    label: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowPlan:
    """An immutable, inspectable workflow execution plan."""

    profile: WorkflowProfile
    ticker: str
    quarter: str
    commands: tuple[WorkflowCommand, ...]


CommandRunner = Callable[[WorkflowCommand], None]


def _script(name: str, *, python_executable: str, structured_narrative_dir: Path) -> list[str]:
    return [python_executable, str(structured_narrative_dir / name)]


def _normalize_tickers(tickers: Iterable[str]) -> list[str]:
    return [ticker.upper() for ticker in tickers]


def plan_workflow(
    profile: WorkflowProfile | str,
    *,
    ticker: str,
    quarter: str,
    force: bool = False,
    bridge_transcript: bool = True,
    export_spine: bool = True,
    research_labels: bool = False,
    spine_tickers: Sequence[str] = PILOT_TICKERS,
    python_executable: str = sys.executable,
    structured_narrative_dir: Path = HERE,
) -> WorkflowPlan:
    """Build a service-callable workflow plan without executing subprocesses.

    ``pre_release`` scores the prior quarter as a dimensions-only baseline.
    ``release_to_call`` extracts the reported quarter and prepares quant
    artifacts without requiring a transcript or Anthropic.
    ``post_call`` scores the transcript while explicitly reusing prepared quant
    data, then optionally refreshes cross-company outputs.
    """

    resolved_profile = WorkflowProfile(profile)
    normalized_ticker = ticker.upper()
    normalized_quarter = normalize_fiscal_period(quarter)
    sn = Path(structured_narrative_dir)
    pipeline = _script(
        "run_company_pipeline.py",
        python_executable=python_executable,
        structured_narrative_dir=sn,
    )
    commands: list[WorkflowCommand] = []

    if resolved_profile is WorkflowProfile.PRE_RELEASE:
        baseline_quarter = prior_fiscal_period(normalized_quarter)
        if baseline_quarter is None:
            raise ValueError(f"Cannot resolve prior fiscal period for {normalized_quarter}")
        baseline_cmd = [
            *pipeline,
            "--ticker",
            normalized_ticker,
            "--baseline-quarter",
            baseline_quarter,
        ]
        if force:
            baseline_cmd.append("--force")
        commands.append(
            WorkflowCommand(
                "Score pre-release prior-quarter baseline",
                tuple(baseline_cmd),
            )
        )

    elif resolved_profile is WorkflowProfile.RELEASE_TO_CALL:
        commands.append(
            WorkflowCommand(
                "Prepare release quant artifacts",
                tuple(
                    [
                        *pipeline,
                        "--ticker",
                        normalized_ticker,
                        "--quant-only",
                        "--append-quarters",
                        normalized_quarter,
                    ]
                ),
            )
        )

    else:
        if bridge_transcript:
            commands.append(
                WorkflowCommand(
                    "Bridge inbox transcripts",
                    tuple(
                        [
                            *_script(
                                "export_inbox_to_transcripts_raw.py",
                                python_executable=python_executable,
                                structured_narrative_dir=sn,
                            ),
                            "--ticker",
                            normalized_ticker,
                        ]
                    ),
                )
            )

        score_cmd = [
            *pipeline,
            "--ticker",
            normalized_ticker,
            "--new-quarter",
            normalized_quarter,
            "--skip-quant",
            "--skip-bridge",
        ]
        if force:
            score_cmd.append("--force")
        commands.append(WorkflowCommand("Score post-call narrative", tuple(score_cmd)))

        if export_spine:
            normalized_spine_tickers = _normalize_tickers(spine_tickers)
            export_argv = [
                *_script(
                    "export_modeling_spine.py",
                    python_executable=python_executable,
                    structured_narrative_dir=sn,
                ),
                "--tickers",
                *normalized_spine_tickers,
            ]
            if research_labels:
                export_argv.append("--include-labels")
            commands.append(
                WorkflowCommand("Export modeling spine", tuple(export_argv))
            )
            if research_labels:
                commands.append(
                    WorkflowCommand(
                        "Evaluate narrative signals",
                        tuple(
                            [
                                *_script(
                                    "evaluate_narrative_signals.py",
                                    python_executable=python_executable,
                                    structured_narrative_dir=sn,
                                ),
                                "--tickers",
                                *normalized_spine_tickers,
                            ]
                        ),
                    )
                )

    return WorkflowPlan(
        profile=resolved_profile,
        ticker=normalized_ticker,
        quarter=normalized_quarter,
        commands=tuple(commands),
    )


def run_command(
    command: WorkflowCommand,
    *,
    cwd: Path = REPO_ROOT,
    env: Mapping[str, str] | None = None,
) -> None:
    """Execute one planned command using the repository subprocess convention."""

    print(f"\n=== {command.label} ===")
    print(" ".join(command.argv))
    subprocess.run(
        list(command.argv),
        cwd=cwd,
        check=True,
        env=dict(env) if env is not None else os.environ.copy(),
    )


def execute_plan(
    plan: WorkflowPlan,
    *,
    runner: CommandRunner | None = None,
) -> None:
    """Execute a plan in order, or pass an injected runner in tests/services."""

    execute = runner or run_command
    for command in plan.commands:
        execute(command)


def run_workflow(
    profile: WorkflowProfile | str,
    **plan_options: object,
) -> WorkflowPlan:
    """Plan and execute a workflow, returning the executed plan."""

    plan = plan_workflow(profile, **plan_options)
    execute_plan(plan)
    return plan
