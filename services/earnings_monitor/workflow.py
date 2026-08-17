"""Lazy bridge to callable Structured Narrative workflow profiles."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from .models import EarningsEvent, TranscriptDocument


class Workflow(Protocol):
    def run(
        self,
        profile: str,
        event: EarningsEvent,
        transcript: TranscriptDocument | None = None,
        *,
        no_prior: bool = False,
    ) -> Mapping[str, Any] | None: ...


class CallableWorkflow:
    def __init__(self, function: Callable[..., Mapping[str, Any] | None]):
        self.function = function

    def run(
        self,
        profile: str,
        event: EarningsEvent,
        transcript: TranscriptDocument | None = None,
        *,
        no_prior: bool = False,
    ) -> Mapping[str, Any] | None:
        return self.function(
            profile=profile,
            event=event,
            transcript=transcript,
            no_prior=no_prior,
        )


class LazyStructuredNarrativeWorkflow:
    """Lazy adapter for ``workflow_profiles.plan_workflow/execute_plan``."""

    def __init__(
        self,
        repo_root: Path | str,
        *,
        runner: Callable[[Any], None] | None = None,
        spine_tickers: tuple[str, ...] | None = None,
    ):
        self.repo_root = Path(repo_root)
        self.runner = runner
        self.spine_tickers = spine_tickers
        self._module: ModuleType | None = None

    def _load_module(self, path: Path) -> ModuleType:
        module_name = f"_earnings_monitor_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot import workflow module {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _resolve(self) -> ModuleType:
        if self._module is not None:
            return self._module
        path = self.repo_root / "Structured Narrative" / "workflow_profiles.py"
        if not path.is_file():
            raise FileNotFoundError(path)
        module = self._load_module(path)
        if not callable(getattr(module, "plan_workflow", None)) or not callable(
            getattr(module, "execute_plan", None)
        ):
            raise RuntimeError("workflow_profiles.py must expose plan_workflow() and execute_plan()")
        self._module = module
        return module

    def available(self) -> tuple[bool, str]:
        try:
            self._resolve()
        except Exception as exc:
            return False, str(exc)
        return True, "workflow_profiles plan_workflow/execute_plan available"

    def transcript_path(self, event: EarningsEvent) -> Path:
        return (
            self.repo_root
            / "Structured Narrative"
            / "transcripts_raw"
            / f"{event.ticker}_{event.fiscal_period}.txt"
        )

    def persist_transcript(self, event: EarningsEvent, transcript: TranscriptDocument) -> Path:
        path = self.transcript_path(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = transcript.content.rstrip() + "\n"
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        os.replace(temporary, path)
        return path

    def run(
        self,
        profile: str,
        event: EarningsEvent,
        transcript: TranscriptDocument | None = None,
        *,
        no_prior: bool = False,
    ) -> Mapping[str, Any]:
        module = self._resolve()
        if profile == "post_call":
            if transcript is None:
                raise ValueError("post_call requires a transcript")
            transcript_path = self.persist_transcript(event, transcript)
        else:
            transcript_path = None
        plan_kwargs = {
            "ticker": event.ticker,
            "quarter": event.fiscal_period,
            "bridge_transcript": False if profile == "post_call" else True,
            "no_prior": bool(no_prior),
        }
        if self.spine_tickers is not None:
            plan_kwargs["spine_tickers"] = self.spine_tickers
        plan = module.plan_workflow(profile, **plan_kwargs)
        module.execute_plan(plan, runner=self.runner)
        return {
            "profile": profile,
            "commands": [command.label for command in plan.commands],
            "transcript_path": str(transcript_path) if transcript_path else None,
        }
