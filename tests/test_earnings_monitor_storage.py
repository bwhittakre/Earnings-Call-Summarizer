from __future__ import annotations

import importlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from services.earnings_monitor import storage
from services.earnings_monitor.dashboard.data import DashboardData, load_operational_events
from services.earnings_monitor.history_import import HistoryImporter


def test_local_artifacts_are_immutable_and_idempotent(tmp_path: Path) -> None:
    store = storage.LocalArtifactStore(tmp_path / "artifacts")
    first = store.put_bytes("AMZN/FY2026-Q1/transcript.txt", b"original")
    repeated = store.put_bytes("AMZN/FY2026-Q1/transcript.txt", b"original")

    assert first.sha256 == repeated.sha256
    assert store.get_bytes(first.key) == b"original"
    assert [ref.key for ref in store.list("AMZN")] == [first.key]

    with pytest.raises(storage.ImmutableArtifactError):
        store.put_bytes(first.key, b"changed")
    with pytest.raises(storage.UnsafeArtifactKey):
        store.put_bytes("../escape", b"no")


def test_dataset_uses_explicit_jsonl_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass
    class Quarter:
        symbol: str
        quarter: str
        score: float

    monkeypatch.setattr(storage, "_parquet_available", lambda: False)
    requested = tmp_path / "company_quarters.parquet"
    result = storage.write_company_quarter_dataset(
        requested,
        [
            Quarter("msft", "fy2026-q1", 1.2),
            {"ticker": "AMZN", "fiscal_period": "FY2025-Q4", "score": -0.3},
        ],
    )

    assert result.format == "jsonl"
    assert result.data_path.suffix == ".jsonl"
    assert not requested.exists()
    assert result.manifest_path.exists()
    rows = storage.read_company_quarter_dataset(requested)
    assert [(row["ticker"], row["fiscal_period"]) for row in rows] == [
        ("AMZN", "FY2025-Q4"),
        ("MSFT", "FY2026-Q1"),
    ]


def _write_history_fixture(root: Path) -> None:
    company = root / "Structured Narrative" / "output" / "AMZN"
    (company / "csv").mkdir(parents=True)
    (company / "json").mkdir(parents=True)
    (company / "csv" / "feature_panel.csv").write_text(
        "ticker,fiscal_period,dimension,llm_level,quant_z_pit,earnings_date\n"
        "AMZN,FY2025-Q4,demand,1.5,0.8,2025-10-30\n",
        encoding="utf-8",
    )
    (company / "json" / "quarter_registry.json").write_text(
        json.dumps(
            {
                "ticker": "AMZN",
                "scored_quarters": {
                    "FY2025-Q4": {
                        "dimensions_scored_at": "2026-01-01",
                        "delta_scored_at": "2026-01-01",
                        "surprise_scored_at": "2026-01-01",
                        "novelty_scored_at": "2026-01-01",
                    },
                    "FY2026-Q1": {
                        "dimensions_scored_at": "2026-01-02",
                    },
                },
                "prior_only_quarters": ["FY2026-Q1"],
                "updated_at": "2026-01-03",
            }
        ),
        encoding="utf-8",
    )


def test_history_import_preserves_missing_and_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_history_fixture(tmp_path)
    monkeypatch.setattr(storage, "_parquet_available", lambda: False)
    importer = HistoryImporter(
        tmp_path,
        tmp_path / "normalized" / "quarters.parquet",
        tickers=("AMZN", "MSFT"),
    )

    records, missing = importer.collect()
    assert missing == ("MSFT",)
    by_period = {record["fiscal_period"]: record for record in records}
    assert by_period["FY2025-Q4"]["history_incomplete"] is False
    assert by_period["FY2026-Q1"]["history_incomplete"] is True
    assert "prior_only" in by_period["FY2026-Q1"]["history_incomplete_flags"]
    provenance = json.loads(by_period["FY2025-Q4"]["history_provenance"])
    assert provenance["panel"]["sha256"]
    assert provenance["registry"]["path"].endswith("quarter_registry.json")

    result = importer.run(prefer_parquet=False)
    assert result.quarters == 2
    assert result.incomplete_quarters == 1
    assert storage.read_company_quarter_dataset(result.dataset.requested_path)


def test_dashboard_modules_import_without_streamlit() -> None:
    app = importlib.import_module("services.earnings_monitor.dashboard.app")
    assert callable(app.render_app)

    data = DashboardData.from_records(
        [
            {
                "ticker": "AMZN",
                "fiscal_period": "FY2026-Q1",
                "dimension": "demand",
                "llm_level": "1.5",
                "quant_z_pit": "0.5",
                "history_incomplete": False,
            },
            {
                "ticker": "MSFT",
                "fiscal_period": "FY2026-Q1",
                "dimension": "demand",
                "llm_level": "-0.5",
                "quant_z_pit": "0.25",
                "history_incomplete": True,
                "history_incomplete_flags": '["missing_novelty_scored"]',
            },
        ]
    )
    assert len(data.event_inbox()) == 2
    assert data.company_history("AMZN")[0]["narrative_level"] == 1.5
    assert len(data.narrative_vs_quant()) == 2
    assert data.audit(incomplete_only=True)[0]["ticker"] == "MSFT"


def test_event_inbox_prefers_live_operational_state(tmp_path: Path) -> None:
    database = tmp_path / "monitor.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE events (
            provider_event_id TEXT, ticker TEXT, fiscal_period TEXT,
            report_at TEXT, call_at TEXT, scheduled_at TEXT, source_url TEXT,
            state TEXT, last_error TEXT, updated_at TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "event-1",
            "MSFT",
            "FY2026-Q4",
            "2026-07-29T20:00:00+00:00",
            "2026-07-29T21:30:00+00:00",
            "2026-07-29T21:30:00+00:00",
            "https://example.test/event-1",
            "awaiting_quant_data",
            "waiting for expected-quarter data",
            "2026-07-29T20:05:00+00:00",
        ),
    )
    connection.commit()
    connection.close()

    operational = load_operational_events(database)
    data = DashboardData.from_records([], operational_events=operational)
    inbox = data.event_inbox()

    assert inbox[0]["ticker"] == "MSFT"
    assert inbox[0]["status"] == "awaiting_quant_data"
    assert inbox[0]["last_error"] == "waiting for expected-quarter data"
