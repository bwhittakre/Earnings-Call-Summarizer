"""Import historical narrative panels into the monitor's normalized dataset."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .storage import (
    DatasetWriteResult,
    normalize_company_quarter_record,
    write_company_quarter_dataset,
)


DEFAULT_TICKERS = ("AMZN", "MSFT", "NVDA", "AAPL")
REQUIRED_SCORE_STAGES = (
    "dimensions_scored_at",
    "delta_scored_at",
    "surprise_scored_at",
    "novelty_scored_at",
)
_PERIOD_RE = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _period_sort_key(period: str) -> tuple[int, int, str]:
    match = _PERIOD_RE.match(str(period))
    if not match:
        return (9999, 9, str(period))
    return (int(match.group(1)), int(match.group(2)), str(period))


def _json_scalar(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class HistoryImportResult:
    dataset: DatasetWriteResult
    tickers: tuple[str, ...]
    quarters: int
    records: int
    incomplete_quarters: int
    missing_tickers: tuple[str, ...]


class HistoryImporter:
    """Discover and import all locally available history for selected companies.

    The importer prefers the generated feature panel because it contains the
    narrative and quantitative fields needed by the dashboard.  The quarter
    registry remains authoritative for completeness.  Registry quarters absent
    from a panel are retained as placeholder records, rather than silently lost.
    """

    def __init__(
        self,
        source_root: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *,
        tickers: Sequence[str] = DEFAULT_TICKERS,
    ) -> None:
        self.source_root = Path(source_root).expanduser().resolve()
        self.destination = Path(destination).expanduser()
        self.tickers = tuple(dict.fromkeys(str(t).strip().upper() for t in tickers))
        self.output_root = self._resolve_output_root()

    def _resolve_output_root(self) -> Path:
        candidates = (
            self.source_root,
            self.source_root / "output",
            self.source_root / "Structured Narrative" / "output",
        )
        def history_score(candidate: Path) -> int:
            score = 0
            for ticker in self.tickers:
                company = candidate / ticker
                expected = (
                    company / "parquet" / "feature_panel.parquet",
                    company / "csv" / "feature_panel.csv",
                    company / "json" / "quarter_registry.json",
                    candidate / f"{ticker}_feature_panel.parquet",
                    candidate / f"{ticker}_feature_panel.csv",
                    candidate / f"{ticker}_quarter_registry.json",
                )
                score += sum(path.is_file() for path in expected)
            return score

        scored = [(history_score(candidate), candidate) for candidate in candidates]
        best_score, best_candidate = max(scored, key=lambda item: item[0])
        if best_score:
            return best_candidate
        # Keep a deterministic path for useful missing-source diagnostics.
        if self.source_root.name.lower() == "structured narrative":
            return self.source_root / "output"
        return self.source_root / "Structured Narrative" / "output"

    def _company_root(self, ticker: str) -> Path:
        return self.output_root / ticker

    def _find_panel(self, ticker: str) -> Path | None:
        company_root = self._company_root(ticker)
        candidates = (
            company_root / "parquet" / "feature_panel.parquet",
            company_root / "csv" / "feature_panel.csv",
            self.output_root / f"{ticker}_feature_panel.parquet",
            self.output_root / f"{ticker}_feature_panel.csv",
        )
        return next((path for path in candidates if path.is_file()), None)

    def _find_registry(self, ticker: str) -> Path | None:
        candidates = (
            self._company_root(ticker) / "json" / "quarter_registry.json",
            self.output_root / f"{ticker}_quarter_registry.json",
        )
        return next((path for path in candidates if path.is_file()), None)

    @staticmethod
    def _read_panel(path: Path) -> list[dict[str, Any]]:
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        if path.suffix.lower() == ".parquet":
            try:
                import pandas as pd  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    f"Cannot read {path}: pandas/pyarrow is unavailable and no CSV fallback exists"
                ) from exc
            return pd.read_parquet(path).to_dict(orient="records")
        raise ValueError(f"Unsupported panel format: {path.suffix}")

    @staticmethod
    def _read_registry(path: Path | None, ticker: str) -> dict[str, Any]:
        if path is None:
            return {"ticker": ticker, "scored_quarters": {}, "prior_only_quarters": []}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError(f"Registry must contain an object: {path}")
        return dict(value)

    @staticmethod
    def _quarter_status(
        period: str,
        registry: Mapping[str, Any],
        *,
        panel_rows_present: bool,
    ) -> tuple[bool, list[str], dict[str, Any]]:
        scored = registry.get("scored_quarters", {})
        details = dict(scored.get(period, {})) if isinstance(scored, Mapping) else {}
        reasons: list[str] = []
        if not panel_rows_present:
            reasons.append("missing_panel_rows")
        if not details:
            reasons.append("missing_registry_entry")
        else:
            for field in REQUIRED_SCORE_STAGES:
                if not details.get(field):
                    reasons.append(f"missing_{field.removesuffix('_at')}")
        return bool(reasons), reasons, details

    def records_for_ticker(self, ticker: str) -> list[dict[str, Any]]:
        ticker = ticker.upper()
        panel_path = self._find_panel(ticker)
        registry_path = self._find_registry(ticker)
        registry = self._read_registry(registry_path, ticker)
        panel_rows = self._read_panel(panel_path) if panel_path else []

        by_period: dict[str, list[dict[str, Any]]] = {}
        for raw in panel_rows:
            candidate = dict(raw)
            candidate.setdefault("ticker", ticker)
            try:
                normalized = normalize_company_quarter_record(candidate)
            except ValueError:
                # A source row without a period cannot be made auditable as a
                # company-quarter record; keep importing all valid rows.
                continue
            by_period.setdefault(normalized["fiscal_period"], []).append(normalized)

        registry_quarters = registry.get("scored_quarters", {})
        periods = set(by_period)
        if isinstance(registry_quarters, Mapping):
            periods.update(str(period).upper() for period in registry_quarters)
        prior_only = {
            str(period).upper() for period in registry.get("prior_only_quarters", [])
        }
        periods.update(prior_only)

        panel_provenance = (
            {
                "path": str(panel_path),
                "format": panel_path.suffix.lower().lstrip("."),
                "sha256": _sha256(panel_path),
                "modified_at": datetime.fromtimestamp(
                    panel_path.stat().st_mtime,
                    timezone.utc,
                ).isoformat(timespec="seconds"),
            }
            if panel_path
            else None
        )
        registry_provenance = (
            {
                "path": str(registry_path),
                "format": "json",
                "sha256": _sha256(registry_path),
                "updated_at": registry.get("updated_at"),
            }
            if registry_path
            else None
        )
        imported_at = _utc_now()
        output: list[dict[str, Any]] = []

        for period in sorted(periods, key=_period_sort_key):
            source_rows = by_period.get(period, [])
            incomplete, reasons, score_details = self._quarter_status(
                period,
                registry,
                panel_rows_present=bool(source_rows),
            )
            if period in prior_only:
                incomplete = True
                reasons.append("prior_only")
            common = {
                "ticker": ticker,
                "fiscal_period": period,
                "history_imported_at": imported_at,
                "history_incomplete": incomplete,
                "history_incomplete_flags": _json_scalar(sorted(set(reasons))),
                "history_prior_only": period in prior_only,
                "history_score_status": _json_scalar(score_details),
                "history_provenance": _json_scalar(
                    {
                        "panel": panel_provenance,
                        "registry": registry_provenance,
                    }
                ),
                "source_path": str(panel_path) if panel_path else "",
                "source_sha256": panel_provenance["sha256"] if panel_provenance else "",
            }
            if source_rows:
                for source_row in source_rows:
                    output.append({**source_row, **common})
            else:
                output.append({**common, "dimension": None, "dimension_group": None})
        return output

    def collect(self) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
        records: list[dict[str, Any]] = []
        missing: list[str] = []
        for ticker in self.tickers:
            company_records = self.records_for_ticker(ticker)
            if not company_records:
                missing.append(ticker)
            records.extend(company_records)
        return records, tuple(missing)

    def run(self, *, prefer_parquet: bool = True) -> HistoryImportResult:
        records, missing = self.collect()
        dataset = write_company_quarter_dataset(
            self.destination,
            records,
            metadata={
                "source_root": str(self.output_root),
                "tickers": list(self.tickers),
                "missing_tickers": list(missing),
            },
            prefer_parquet=prefer_parquet,
        )
        quarter_states = {
            (row["ticker"], row["fiscal_period"]): bool(row["history_incomplete"])
            for row in records
        }
        return HistoryImportResult(
            dataset=dataset,
            tickers=self.tickers,
            quarters=len(quarter_states),
            records=len(records),
            incomplete_quarters=sum(quarter_states.values()),
            missing_tickers=missing,
        )


def import_history(
    source_root: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    tickers: Sequence[str] = DEFAULT_TICKERS,
    prefer_parquet: bool = True,
) -> HistoryImportResult:
    return HistoryImporter(
        source_root,
        destination,
        tickers=tickers,
    ).run(prefer_parquet=prefer_parquet)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        default=Path(__file__).resolve().parents[2],
        type=Path,
        help="Repository, Structured Narrative, or output directory",
    )
    parser.add_argument(
        "--destination",
        default=Path("data/earnings_monitor/company_quarters.parquet"),
        type=Path,
    )
    parser.add_argument("--tickers", nargs="+", default=list(DEFAULT_TICKERS))
    parser.add_argument("--jsonl", action="store_true", help="Force portable JSONL output")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = import_history(
        args.source_root,
        args.destination,
        tickers=args.tickers,
        prefer_parquet=not args.jsonl,
    )
    print(
        json.dumps(
            {
                "data_path": str(result.dataset.data_path),
                "format": result.dataset.format,
                "records": result.records,
                "quarters": result.quarters,
                "incomplete_quarters": result.incomplete_quarters,
                "missing_tickers": result.missing_tickers,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
