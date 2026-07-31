"""Assemble decision-ready company-quarter output from durable artifacts."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from .models import EarningsEvent
from .storage import read_company_quarter_dataset


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if math.isfinite(number) else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _text(row: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return None


class DecisionOutputAssembler:
    """Build a compact scorecard without requiring pandas at notification time."""

    def __init__(
        self,
        dataset_path: Path | str | None,
        structured_output_root: Path | str | None,
    ) -> None:
        self.dataset_path = Path(dataset_path) if dataset_path else None
        self.output_root = Path(structured_output_root) if structured_output_root else None

    def _rows(self, event: EarningsEvent) -> tuple[list[dict[str, Any]], list[str]]:
        issues: list[str] = []
        if self.dataset_path is None:
            return [], ["dataset_not_configured"]
        try:
            rows = read_company_quarter_dataset(self.dataset_path)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            return [], [f"dataset_unavailable:{type(exc).__name__}"]
        selected = [
            row
            for row in rows
            if str(row.get("ticker", "")).upper() == event.ticker
            and str(row.get("fiscal_period", "")).upper() == event.fiscal_period
        ]
        if not selected:
            issues.append("quarter_missing_from_dataset")
        return selected, issues

    def _registry(self, event: EarningsEvent) -> tuple[dict[str, Any], list[str]]:
        if self.output_root is None:
            return {}, ["structured_output_not_configured"]
        candidates = (
            self.output_root / event.ticker / "json" / "quarter_registry.json",
            self.output_root / f"{event.ticker}_quarter_registry.json",
        )
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            return {}, ["quarter_registry_missing"]
        try:
            registry = json.loads(path.read_text(encoding="utf-8"))
            details = registry.get("scored_quarters", {}).get(event.fiscal_period, {})
            return dict(details) if isinstance(details, Mapping) else {}, []
        except (OSError, ValueError, TypeError):
            return {}, ["quarter_registry_invalid"]

    def _artifact_links(self, event: EarningsEvent) -> list[str]:
        if self.output_root is None:
            return []
        company = self.output_root / event.ticker
        if not company.is_dir():
            return []
        links: list[str] = []
        for path in sorted(company.rglob("*")):
            if (
                path.is_file()
                and path.suffix.lower() in {".html", ".pdf", ".json"}
                and (
                    event.fiscal_period.lower() in path.name.lower()
                    or path.name in {"feature_panel.html", "quarter_registry.json"}
                )
            ):
                links.append(path.resolve().as_uri())
            if len(links) == 5:
                break
        return links

    def assemble(self, event: EarningsEvent) -> dict[str, Any]:
        rows, issues = self._rows(event)
        registry, registry_issues = self._registry(event)
        issues.extend(registry_issues)
        dimensions: list[dict[str, Any]] = []
        for row in sorted(rows, key=lambda item: str(item.get("dimension") or "")):
            dimension = _text(row, "dimension", "dimension_group")
            if not dimension:
                continue
            quant_z = _number(row.get("quant_z_pit"))
            if quant_z is None:
                quant_z = _number(row.get("quant_z"))
            missing = [
                name
                for name, value in (
                    ("quant_z", quant_z),
                    ("narrative_level", _number(row.get("llm_level"))),
                    ("narrative_change", _number(row.get("change_magnitude"))),
                )
                if value is None
            ]
            evidence = _text(
                row,
                "surprise_rationale",
                "delta_rationale",
                "level_rationale",
                "novelty_rationale",
                "rationale",
                "evidence",
                "quote",
                "excerpt",
            )
            dimensions.append(
                {
                    "dimension": dimension,
                    "measure": _number(
                        row.get("quant_value", row.get("value", row.get("actual")))
                    ),
                    "quant_z": quant_z,
                    "narrative_level": _number(row.get("llm_level")),
                    "narrative_change": _number(row.get("change_magnitude")),
                    "narrative_quant_gap": _number(row.get("narrative_quant_gap")),
                    "divergence": any(
                        _truthy(row.get(name))
                        for name in (
                            "any_quant_divergence",
                            "level_diverges",
                            "delta_diverges",
                            "surprise_diverges",
                            "is_divergence",
                        )
                    ),
                    "evidence": evidence[:280] if evidence else None,
                    "evidence_supported_pct": next(
                        (
                            value
                            for name in (
                                "surprise_evidence_supported_pct",
                                "delta_evidence_supported_pct",
                                "level_evidence_supported_pct",
                                "novelty_evidence_supported_pct",
                            )
                            if (value := _number(row.get(name))) is not None
                        ),
                        None,
                    ),
                    "missing": missing,
                }
            )
        as_of = next(
            (
                _text(row, "as_of_date", "earnings_date", "history_imported_at")
                for row in rows
                if _text(row, "as_of_date", "earnings_date", "history_imported_at")
            ),
            None,
        )
        incomplete_flags = {
            flag
            for row in rows
            for flag in self._decode_flags(row.get("history_incomplete_flags"))
        }
        if any(_truthy(row.get("history_incomplete")) for row in rows):
            issues.append("history_incomplete")
        issues.extend(sorted(incomplete_flags))
        required_stages = (
            "dimensions_scored_at",
            "delta_scored_at",
            "surprise_scored_at",
            "novelty_scored_at",
        )
        missing_stages = [stage for stage in required_stages if registry and not registry.get(stage)]
        issues.extend(f"missing_{stage.removesuffix('_at')}" for stage in missing_stages)
        missing_dimension_values = sum(bool(row["missing"]) for row in dimensions)
        complete = bool(dimensions) and not issues and missing_dimension_values == 0
        return {
            "ticker": event.ticker,
            "fiscal_period": event.fiscal_period,
            "as_of": as_of,
            "dimensions": dimensions,
            "divergences": [row for row in dimensions if row["divergence"]],
            "completion": {
                "complete": complete,
                "dimension_count": len(dimensions),
                "dimensions_with_missing_values": missing_dimension_values,
                "issues": list(dict.fromkeys(issues)),
                "registry": registry,
            },
            "artifact_links": self._artifact_links(event),
        }

    @staticmethod
    def _decode_flags(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        if not value:
            return []
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError):
            return [str(value)]
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
