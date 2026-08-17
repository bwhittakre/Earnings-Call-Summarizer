from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from services.earnings_monitor.config import MonitorConfig
from services.earnings_monitor.dashboard.research_data import load_book_ranks_bundle
from services.earnings_monitor.freshness import AlwaysFreshProbe
from services.earnings_monitor.models import (
    EarningsEvent,
    EventState,
    MonitoredEvent,
    TranscriptDocument,
    TranscriptStatus,
)
from services.earnings_monitor.service import EarningsMonitor
from services.earnings_monitor.state import OperationalState
from services.earnings_monitor.transcripts import transcript_fingerprint

UTC = timezone.utc
SN = Path(__file__).resolve().parents[1] / "Structured Narrative"
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from signal_pack import SignalPack, FALLBACK_HYPOTHESES  # noqa: E402
import build_book_ranks as bbr  # noqa: E402


def _config(tmp_path: Path, **overrides) -> MonitorConfig:
    values = {
        "repo_root": tmp_path,
        "database_path": tmp_path / "state.sqlite3",
        "inbox_path": tmp_path / "inbox",
        "stabilization_seconds": 0,
        "minimum_transcript_chars": 10,
        "research_regen_after_post_call": True,
        "tickers": ("AAAA", "BBBB", "CCCC", "DDDD"),
    }
    values.update(overrides)
    return MonitorConfig(**values)


def _synthetic_stack(*, as_of: str = "2026-07-22", call_avail: str = "2026-07-15") -> pd.DataFrame:
    rows = []
    # Four peers in 2026-Q2; demand quant_z_pit ranks D > C > B > A
    z_by_ticker = {"AAAA": 0.0, "BBBB": 1.0, "CCCC": 2.0, "DDDD": 3.0}
    for ticker, z in z_by_ticker.items():
        for dimension, agree in (
            ("demand", z / 3.0),
            ("margins", z / 3.0),
            ("guidance", z / 3.0),
        ):
            rows.append(
                {
                    "ticker": ticker,
                    "fiscal_period": "FY2026-Q2",
                    "period_end_calendar_quarter": "2026-Q2",
                    "dimension": dimension,
                    "quant_z_pit": z if dimension == "demand" else None,
                    "agrees_with_quant": agree,
                    "investable_ready": True,
                    "investable_as_of_date": as_of,
                    "call_feature_available_date": call_avail,
                    "first_print": False,
                    "no_prior": False,
                    "exclusion_reason": "",
                    "earnings_date": call_avail,
                }
            )
    return pd.DataFrame(rows)


def test_cross_section_z_and_dense_rank_stable():
    z, rank = bbr._cross_section_z_and_rank(pd.Series([0.0, 1.0, 2.0, 3.0]))
    assert list(rank) == [4, 3, 2, 1]
    assert abs(float(z.iloc[-1]) - float(z.max())) < 1e-9


def test_build_book_ranks_synthetic_four_tickers(monkeypatch):
    monkeypatch.setattr(bbr, "stack_book_panels", lambda tickers: _synthetic_stack())
    pack = SignalPack(
        pack_id="production_v1",
        hypotheses=FALLBACK_HYPOTHESES,
        min_names=3,
    )
    frame, summary = bbr.build_book_ranks(
        ["AAAA", "BBBB", "CCCC", "DDDD"],
        pack=pack,
        trigger_ticker="CCCC",
        trigger_period="FY2026-Q2",
        now=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        mode="investable_asof",
    )
    assert summary["skipped_reason"] is None
    assert summary["pack_id"] == "production_v1"
    assert summary["rank_mode"] == "investable_asof"
    assert summary["as_of_date"] == "2026-07-22"
    assert summary["period_bucket"] == "2026-Q2"
    assert summary["n_peers"] == 4
    demand_qz = frame[
        (frame["signal"] == "quant_z_pit")
        & (frame["dimension"] == "demand")
        & (frame["eligible"] == True)  # noqa: E712
    ].set_index("ticker")
    assert int(demand_qz.loc["DDDD", "rank"]) == 1
    assert int(demand_qz.loc["AAAA", "rank"]) == 4
    assert len(frame[frame["eligible"] == True]) == 4 * 4  # noqa: E712


def test_investable_asof_awaits_future_as_of(monkeypatch):
    monkeypatch.setattr(
        bbr,
        "stack_book_panels",
        lambda tickers: _synthetic_stack(as_of="2026-12-01"),
    )
    pack = SignalPack(
        pack_id="production_v1",
        hypotheses=FALLBACK_HYPOTHESES,
        min_names=3,
    )
    frame, summary = bbr.build_book_ranks(
        ["AAAA", "BBBB", "CCCC", "DDDD"],
        pack=pack,
        now=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        mode="investable_asof",
    )
    assert frame.empty
    assert summary["skipped_reason"] == "awaiting_investable_asof"
    assert summary["pending"] is True
    assert summary["preserve_prior_artifacts"] is True


def test_investable_asof_force_builds_before_date(monkeypatch):
    monkeypatch.setattr(
        bbr,
        "stack_book_panels",
        lambda tickers: _synthetic_stack(as_of="2026-12-01"),
    )
    pack = SignalPack(
        pack_id="production_v1",
        hypotheses=FALLBACK_HYPOTHESES,
        min_names=3,
    )
    frame, summary = bbr.build_book_ranks(
        ["AAAA", "BBBB", "CCCC", "DDDD"],
        pack=pack,
        now=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        mode="investable_asof",
        force_asof=True,
    )
    assert summary["skipped_reason"] is None
    assert not frame.empty
    assert summary["as_of_date"] == "2026-12-01"


def test_load_book_ranks_bundle_empty_safe(tmp_path: Path):
    root = tmp_path / "output" / "cross_company"
    root.mkdir(parents=True)
    bundle = load_book_ranks_bundle(history_source=tmp_path / "output")
    assert bundle.rows == []
    assert bundle.available is False
    assert "book_ranks" in bundle.empty_message.lower() or "Book ranks" in bundle.empty_message
    assert bundle.missing


def test_load_book_ranks_bundle_reads_artifacts(tmp_path: Path):
    root = tmp_path / "output" / "cross_company"
    (root / "csv").mkdir(parents=True)
    (root / "json").mkdir(parents=True)
    (root / "csv" / "book_ranks.csv").write_text(
        "pack_id,ticker,signal,dimension,rank,cs_z,n_peers\n"
        "production_v1,MSFT,quant_z_pit,demand,1,1.2,4\n",
        encoding="utf-8",
    )
    (root / "json" / "book_ranks_summary.json").write_text(
        '{"pack_id":"production_v1","built_at":"2026-08-10T12:00:00Z","n_peers":4}\n',
        encoding="utf-8",
    )
    bundle = load_book_ranks_bundle(history_source=tmp_path / "output")
    assert bundle.available
    assert len(bundle.rows) == 1
    assert bundle.meta["pack_id"] == "production_v1"
    assert bundle.meta["n_peers"] == 4


def test_readable_csv_includes_metric_key_on_right(monkeypatch):
    monkeypatch.setattr(bbr, "stack_book_panels", lambda tickers: _synthetic_stack())
    pack = SignalPack(
        pack_id="production_v1",
        hypotheses=FALLBACK_HYPOTHESES,
        min_names=3,
    )
    frame, _summary = bbr.build_book_ranks(
        ["AAAA", "BBBB", "CCCC", "DDDD"],
        pack=pack,
    )
    readable = bbr.frame_for_readable_csv(frame)
    assert "Rank (1=highest)" in readable.columns
    assert "Metric" in readable.columns
    assert "Meaning" in readable.columns
    assert readable.iloc[0]["Metric"] == "As-of date"
    assert "t+7" in str(readable.iloc[0]["Meaning"]).lower()


def test_loader_normalizes_human_csv_headers(tmp_path: Path):
    root = tmp_path / "output" / "cross_company"
    (root / "csv").mkdir(parents=True)
    (root / "json").mkdir(parents=True)
    (root / "csv" / "book_ranks.csv").write_text(
        "Ticker,Signal,Dimension,Rank (1=highest),Cross-section z,Peer count,Eligible,,Metric,Meaning\n"
        "MSFT,quant_z_pit,demand,1,1.2,4,True,,Rank (1=highest),Dense rank\n",
        encoding="utf-8",
    )
    (root / "json" / "book_ranks_summary.json").write_text(
        '{"pack_id":"production_v1","built_at":"2026-08-10T12:00:00Z"}\n',
        encoding="utf-8",
    )
    bundle = load_book_ranks_bundle(history_source=tmp_path / "output")
    assert len(bundle.rows) == 1
    assert bundle.rows[0]["ticker"] == "MSFT"
    assert bundle.rows[0]["rank"] == 1 or bundle.rows[0]["rank"] == 1.0


def _run_post_call(
    tmp_path: Path,
    *,
    status: TranscriptStatus,
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    now = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)
    earnings_event = EarningsEvent(
        "event-ranks",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=2),
        call_at=now - timedelta(hours=1),
    )
    transcript = TranscriptDocument(
        "AAPL",
        "FY2026-Q3",
        "completed transcript long enough for post-call scoring path",
        "quartr",
        "doc-ranks",
        status=status,
    )
    fingerprint = transcript_fingerprint(transcript.content)
    spy = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(
        "services.earnings_monitor.book_ranks.run_book_ranks_subprocess",
        spy,
    )

    class Provider:
        def list_events(self, tickers, *, since, until):
            return []

        def get_transcript(self, requested):
            return transcript

    class Workflow:
        def run(self, profile, requested, transcript=None, **kwargs):
            return {"ok": True}

    (tmp_path / "Structured Narrative").mkdir(exist_ok=True)
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    monitored = MonitoredEvent(
        earnings_event,
        state=EventState.POST_CALL_QUEUED,
        transcript_fingerprint=fingerprint,
        transcript_observed_at=now - timedelta(minutes=10),
    )
    state.upsert_event(monitored)
    state.enqueue(
        idempotency_key=f"post:event-ranks:{status.value}",
        provider_event_id="event-ranks",
        payload={"stage": "post_call", "fingerprint": fingerprint},
        max_attempts=1,
        available_at=now,
    )
    service = EarningsMonitor(
        config=_config(tmp_path),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=Workflow(),
        clock=lambda: now,
    )
    assert service.run_next_job()
    return spy


def test_final_post_call_runs_book_ranks(tmp_path, monkeypatch):
    spy = _run_post_call(tmp_path, status=TranscriptStatus.FINAL, monkeypatch=monkeypatch)
    assert spy.call_count == 1
    kwargs = spy.call_args.kwargs
    assert kwargs["trigger_ticker"] == "AAPL"
    assert kwargs["trigger_period"] == "FY2026-Q3"


def test_live_post_call_skips_book_ranks(tmp_path, monkeypatch):
    spy = _run_post_call(tmp_path, status=TranscriptStatus.LIVE, monkeypatch=monkeypatch)
    assert spy.call_count == 0
