"""Pure data access and transformation helpers for the monitor dashboard."""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

from ..storage import read_company_quarter_dataset, record_to_dict


_PERIOD_RE = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)


def _period_key(value: Any) -> tuple[int, int, str]:
    text = str(value or "")
    match = _PERIOD_RE.match(text)
    if not match:
        return (-1, -1, text)
    return (int(match.group(1)), int(match.group(2)), text)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _mean(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [value for row in rows if (value := _number(row.get(key))) is not None]
    return round(fmean(values), 4) if values else None


def _decode_json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


@dataclass
class DashboardData:
    """A stable dashboard facade over loose record dictionaries."""

    rows: list[dict[str, Any]]
    operational_events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_records(
        cls,
        records: Iterable[Any],
        *,
        operational_events: Iterable[Any] = (),
    ) -> "DashboardData":
        return cls(
            [record_to_dict(record) for record in records],
            [record_to_dict(event) for event in operational_events],
        )

    @property
    def tickers(self) -> list[str]:
        return sorted({str(row.get("ticker", "")).upper() for row in self.rows if row.get("ticker")})

    def _group_quarters(
        self,
        *,
        ticker: str | None = None,
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        ticker_filter = ticker.upper() if ticker else None
        for row in self.rows:
            row_ticker = str(row.get("ticker", "")).upper()
            period = str(row.get("fiscal_period", ""))
            if not row_ticker or not period or (ticker_filter and row_ticker != ticker_filter):
                continue
            grouped.setdefault((row_ticker, period), []).append(row)
        return grouped

    def event_inbox(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self.operational_events:
            events = [
                {
                    "ticker": str(row.get("ticker", "")).upper(),
                    "fiscal_period": row.get("fiscal_period"),
                    "report_at": row.get("report_at"),
                    "call_at": row.get("call_at", row.get("scheduled_at")),
                    "status": row.get("state"),
                    "last_error": row.get("last_error"),
                    "source_url": row.get("source_url"),
                    "updated_at": row.get("updated_at"),
                }
                for row in self.operational_events
            ]
            events.sort(
                key=lambda row: (
                    str(row.get("call_at") or ""),
                    str(row.get("ticker") or ""),
                ),
                reverse=True,
            )
            return events[:limit]
        events: list[dict[str, Any]] = []
        for (ticker, period), rows in self._group_quarters().items():
            first = rows[0]
            divergence_count = sum(
                _truthy(row.get("any_quant_divergence", row.get("is_divergence")))
                for row in rows
            )
            events.append(
                {
                    "ticker": ticker,
                    "fiscal_period": period,
                    "earnings_date": first.get("earnings_date", first.get("as_of_date")),
                    "status": "incomplete"
                    if any(_truthy(row.get("history_incomplete")) for row in rows)
                    else "ready",
                    "dimensions": sum(row.get("dimension") not in (None, "") for row in rows),
                    "divergences": divergence_count,
                    "mean_narrative_level": _mean(rows, "llm_level"),
                    "mean_quant_z": _mean(rows, "quant_z_pit")
                    if any(row.get("quant_z_pit") not in (None, "") for row in rows)
                    else _mean(rows, "quant_z"),
                }
            )
        events.sort(
            key=lambda row: (
                str(row.get("earnings_date") or ""),
                _period_key(row["fiscal_period"]),
                row["ticker"],
            ),
            reverse=True,
        )
        return events[:limit]

    def company_history(self, ticker: str) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for (_, period), rows in self._group_quarters(ticker=ticker).items():
            first = rows[0]
            history.append(
                {
                    "fiscal_period": period,
                    "period_end_date": first.get("period_end_date"),
                    "earnings_date": first.get("earnings_date", first.get("as_of_date")),
                    "dimensions": sum(row.get("dimension") not in (None, "") for row in rows),
                    "narrative_level": _mean(rows, "llm_level"),
                    "narrative_change": _mean(rows, "change_magnitude"),
                    "quant_z": _mean(rows, "quant_z_pit")
                    if any(row.get("quant_z_pit") not in (None, "") for row in rows)
                    else _mean(rows, "quant_z"),
                    "narrative_quant_gap": _mean(rows, "narrative_quant_gap"),
                    "incomplete": any(_truthy(row.get("history_incomplete")) for row in rows),
                }
            )
        history.sort(key=lambda row: _period_key(row["fiscal_period"]))
        return history

    def cross_company(self, *, latest_periods: int = 12) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for ticker in self.tickers:
            history = self.company_history(ticker)
            selected = history[-latest_periods:] if latest_periods > 0 else history
            summary.append(
                {
                    "ticker": ticker,
                    "quarters": len(history),
                    "latest_period": history[-1]["fiscal_period"] if history else None,
                    "mean_narrative_level": _mean(selected, "narrative_level"),
                    "mean_narrative_change": _mean(selected, "narrative_change"),
                    "mean_quant_z": _mean(selected, "quant_z"),
                    "mean_narrative_quant_gap": _mean(selected, "narrative_quant_gap"),
                    "incomplete_quarters": sum(_truthy(row.get("incomplete")) for row in history),
                }
            )
        return summary

    def narrative_vs_quant(
        self,
        *,
        tickers: Sequence[str] | None = None,
        dimension: str | None = None,
    ) -> list[dict[str, Any]]:
        allowed = {ticker.upper() for ticker in tickers} if tickers else None
        points: list[dict[str, Any]] = []
        for row in self.rows:
            ticker = str(row.get("ticker", "")).upper()
            if allowed is not None and ticker not in allowed:
                continue
            if dimension and str(row.get("dimension", "")) != dimension:
                continue
            narrative = _number(row.get("llm_level"))
            quant = _number(row.get("quant_z_pit"))
            if quant is None:
                quant = _number(row.get("quant_z"))
            if narrative is None or quant is None:
                continue
            points.append(
                {
                    "ticker": ticker,
                    "fiscal_period": row.get("fiscal_period"),
                    "dimension": row.get("dimension"),
                    "narrative_level": narrative,
                    "quant_z": quant,
                    "gap": _number(row.get("narrative_quant_gap")),
                    "divergence": _truthy(
                        row.get("any_quant_divergence", row.get("is_divergence"))
                    ),
                }
            )
        return points

    def audit(self, *, incomplete_only: bool = False) -> list[dict[str, Any]]:
        audits: list[dict[str, Any]] = []
        for (ticker, period), rows in self._group_quarters().items():
            first = rows[0]
            incomplete = any(_truthy(row.get("history_incomplete")) for row in rows)
            if incomplete_only and not incomplete:
                continue
            flags: set[str] = set()
            for row in rows:
                decoded = _decode_json(row.get("history_incomplete_flags"), [])
                if isinstance(decoded, list):
                    flags.update(str(item) for item in decoded)
            provenance = _decode_json(first.get("history_provenance"), {})
            panel = provenance.get("panel") or {} if isinstance(provenance, dict) else {}
            registry = provenance.get("registry") or {} if isinstance(provenance, dict) else {}
            audits.append(
                {
                    "ticker": ticker,
                    "fiscal_period": period,
                    "incomplete": incomplete,
                    "flags": ", ".join(sorted(flags)),
                    "panel_source": panel.get("path", first.get("source_path")),
                    "panel_sha256": panel.get("sha256", first.get("source_sha256")),
                    "registry_source": registry.get("path"),
                    "imported_at": first.get("history_imported_at"),
                }
            )
        audits.sort(key=lambda row: (row["ticker"], _period_key(row["fiscal_period"])))
        return audits

    @property
    def dimensions(self) -> list[str]:
        return sorted(
            {str(row["dimension"]) for row in self.rows if row.get("dimension") not in (None, "")}
        )


def default_dataset_path() -> Path:
    configured = os.environ.get("EARNINGS_MONITOR_DATASET")
    if configured:
        return Path(configured).expanduser()
    return Path("data/earnings_monitor/company_quarters.parquet")


def default_operational_db_path() -> Path:
    configured = os.environ.get("EARNINGS_MONITOR_DB")
    if configured:
        return Path(configured).expanduser()
    return Path("services/earnings_monitor/state/monitor.sqlite3")


def load_operational_events(path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    database = Path(path or default_operational_db_path())
    if not database.is_file():
        return []
    try:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT provider_event_id, ticker, fiscal_period, report_at, call_at,
                       scheduled_at, source_url, state, last_error, updated_at
                FROM events
                ORDER BY call_at DESC
                """
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def load_dashboard_data(
    path: str | os.PathLike[str] | None = None,
    *,
    operational_db_path: str | os.PathLike[str] | None = None,
) -> DashboardData:
    return DashboardData.from_records(
        read_company_quarter_dataset(path or default_dataset_path()),
        operational_events=load_operational_events(operational_db_path),
    )
