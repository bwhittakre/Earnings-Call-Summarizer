"""MCP pull checklist + on-disk conference ingest (no REST)."""

from __future__ import annotations

from pathlib import Path

from services.earnings_monitor.conf_desk import ingest_on_disk_conferences
from services.earnings_monitor.onboard_pull import (
    LOOKBACK_START_PERIOD,
    discover_conference_events,
    pull_checklist,
    write_conference_transcript,
)


def test_pull_checklist_targets_2016_or_all_available() -> None:
    checklist = pull_checklist(ticker="crwv")
    assert checklist["ticker"] == "CRWV"
    assert checklist["lookback_start"] == LOOKBACK_START_PERIOD == "2016-Q1"
    assert "every available" in checklist["lookback_rule"]
    assert checklist["source"] == "quartr_mcp"
    assert "independent" in checklist["onboard_after"]
    assert Path(checklist["conference_dir"]) == Path("data") / "conf_transcripts" / "CRWV"


def test_write_conference_transcript_updates_manifest(tmp_path: Path) -> None:
    dest = write_conference_transcript(
        tmp_path,
        ticker="NEWCO",
        event_id=123,
        event_date="2026-03-04",
        event_name="Test Conf",
        payload={"eventId": 123, "text": "hello"},
    )
    assert dest.is_file()
    events = discover_conference_events(tmp_path, "NEWCO")
    assert len(events) == 1
    assert events[0]["event_id"] == 123
    assert events[0]["date"] == "2026-03-04"
    assert Path(events[0]["path"]).is_file()


def test_ingest_skips_missing_date(tmp_path: Path) -> None:
    write_conference_transcript(
        tmp_path,
        ticker="NEWCO",
        event_id=9,
        event_date="",
        event_name="No date",
        payload={"eventId": 9},
    )
    result = ingest_on_disk_conferences(repo_root=tmp_path, ticker="NEWCO")
    assert result["ingested"] == []
    assert result["skipped"][0]["reason"] == "missing_date"


def test_ingest_uses_transcript_file_not_rest(tmp_path: Path, monkeypatch) -> None:
    dest = write_conference_transcript(
        tmp_path,
        ticker="NEWCO",
        event_id=44,
        event_date="2026-01-15",
        event_name="CES",
        payload={"eventId": 44},
    )
    seen: list[dict] = []

    def fake_ingest(ticker, event_id, date, name, **kwargs):
        seen.append(
            {
                "ticker": ticker,
                "event_id": event_id,
                "date": date,
                "name": name,
                "extract_only": kwargs.get("extract_only"),
                "transcript_file": Path(kwargs["transcript_file"]),
            }
        )
        return [{"ticker": ticker, "fiscal_period": f"CONF-{date}"}]

    monkeypatch.setattr("scripts._desk_conf_ingest.ingest_conference", fake_ingest)
    result = ingest_on_disk_conferences(repo_root=tmp_path, ticker="NEWCO")
    assert result["ingested"][0]["event_id"] == 44
    assert seen[0]["extract_only"] is True
    assert seen[0]["transcript_file"] == dest


def test_ingest_skips_already_ingested(tmp_path: Path, monkeypatch) -> None:
    write_conference_transcript(
        tmp_path,
        ticker="NEWCO",
        event_id=7,
        event_date="2025-08-27",
        event_name="Done",
        payload={"eventId": 7},
    )
    cue = tmp_path / "data" / "desk_conf_cue_NEWCO.json"
    cue.parent.mkdir(parents=True, exist_ok=True)
    cue.write_text(
        '{"events": [{"event_id": 7, "ingested_at": "2026-01-01T00:00:00Z"}]}',
        encoding="utf-8",
    )
    called = []
    monkeypatch.setattr(
        "scripts._desk_conf_ingest.ingest_conference",
        lambda *a, **k: called.append(1),
    )
    result = ingest_on_disk_conferences(repo_root=tmp_path, ticker="NEWCO")
    assert called == []
    assert result["skipped"][0]["reason"] == "already_ingested"
