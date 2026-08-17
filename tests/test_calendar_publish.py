from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.earnings_monitor.automation_watchlist import Watchlist
from services.earnings_monitor.calendar_publish import (
    CallableEventGateway,
    JsonEventsDumpGateway,
    MergedJsonDirGateway,
    list_due_sweep_targets,
    publish_calendar,
    quartr_row_to_manifest,
    resolve_publish_tickers,
    write_due_worklist,
)
from services.earnings_monitor.eligibility import (
    eligible_discovery_tickers,
    list_overlay_tickers,
)
from services.earnings_monitor.config import MonitorConfig
from services.earnings_monitor.providers import WatchedEventManifestProvider


def _quartr_earnings(
    *,
    event_id: str = "665958",
    ticker: str = "OPAL",
    fiscal_year: int = 2026,
    event_type: str = "q_2",
    call_at: datetime | None = None,
) -> dict:
    call = call_at or (datetime.now(timezone.utc) + timedelta(days=3))
    stamp = call.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": int(event_id) if event_id.isdigit() else event_id,
        "title": f"Q{event_type[-1]} {fiscal_year}",
        "eventType": event_type,
        "parentEventType": "earnings_call",
        "fiscalYear": fiscal_year,
        "ticker": ticker,
        "companyId": 15164,
        "url": f"https://web.quartr.com/companies/15164/events/{event_id}/overview",
        "contentDates": [
            {"contentType": "report", "date": stamp},
            {"contentType": "audio", "date": stamp},
        ],
    }


def test_quartr_row_maps_q1_q4_fiscal_periods():
    cases = (
        ("q_1", 2026, "FY2026-Q1"),
        ("q_2", 2026, "FY2026-Q2"),
        ("q_3", 2026, "FY2026-Q3"),
        ("q_4", 2025, "FY2025-Q4"),
    )
    for event_type, year, expected in cases:
        row = _quartr_earnings(event_type=event_type, fiscal_year=year)
        manifest = quartr_row_to_manifest(row)
        assert manifest is not None
        assert manifest["fiscal_period"] == expected
        assert manifest["schema_version"] == 1
        assert manifest["provider_event_id"] == "665958"


def test_publish_skips_no_overlay_and_writes_valid_manifest(tmp_path: Path):
    overlays = tmp_path / "overlays"
    overlays.mkdir()
    (overlays / "OPAL.json").write_text("{}", encoding="utf-8")
    events_dir = tmp_path / "events"
    call_at = datetime(2026, 8, 12, 16, 0, tzinfo=timezone.utc)
    dump = tmp_path / "events.json"
    dump.write_text(
        json.dumps(
            [
                _quartr_earnings(ticker="OPAL", call_at=call_at),
                _quartr_earnings(
                    event_id="999",
                    ticker="ZZZNO",
                    call_at=call_at,
                ),
            ]
        ),
        encoding="utf-8",
    )
    tickers = resolve_publish_tickers(
        tickers=["OPAL", "ZZZNO"],
        repo_root=tmp_path,
        overlay_dir=overlays,
    )
    assert tickers == ("OPAL",)
    gateway = JsonEventsDumpGateway(dump)
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    results = publish_calendar(
        gateway,
        tickers=tickers,
        events_dir=events_dir,
        horizon_days=30,
        now=now,
    )
    assert len(results) == 1
    assert results[0].ticker == "OPAL"
    assert results[0].fiscal_period == "FY2026-Q2"
    path = Path(results[0].path)
    assert path.is_file()
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["provider_event_id"] == "665958"
    # Watched provider must accept the published shape.
    provider = WatchedEventManifestProvider(events_dir)
    found = provider.list_events(
        ["OPAL"],
        since=now - timedelta(days=1),
        until=now + timedelta(days=30),
    )
    assert len(found) == 1
    assert found[0].provider_event_id == "665958"


def test_list_due_sweep_targets_near_call():
    now = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)
    near = now + timedelta(hours=1)
    far = now + timedelta(days=10)

    def fetch(ticker: str):
        if ticker != "OPAL":
            return []
        return [
            _quartr_earnings(event_id="1", call_at=near),
            _quartr_earnings(event_id="2", call_at=far),
        ]

    due = list_due_sweep_targets(
        CallableEventGateway(fetch),
        tickers=["OPAL"],
        within_hours=6.0,
        now=now,
    )
    assert [item.event_id for item in due] == ["1"]


def test_eligible_discovery_tickers_book_intersect_overlays(tmp_path: Path):
    overlays = tmp_path / "Structured Narrative" / "config" / "company_overlays"
    overlays.mkdir(parents=True)
    (overlays / "OPAL.json").write_text("{}", encoding="utf-8")
    (overlays / "STRW.json").write_text("{}", encoding="utf-8")
    sector = tmp_path / "config" / "sectors"
    sector.mkdir(parents=True)
    (sector / "xlk_tech.txt").write_text("OPAL\nMSFT\n", encoding="utf-8")
    config = MonitorConfig(
        repo_root=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        inbox_path=tmp_path / "inbox",
        tickers=("MSFT", "AAPL"),
        research_sector="xlk_tech",
    )
    assert list_overlay_tickers(overlays) == frozenset({"OPAL", "STRW"})
    # Book = env tickers ∪ sector → MSFT, AAPL, OPAL; ∩ overlays → OPAL only
    # (MSFT has no overlay; STRW overlay but not in book).
    eligible = eligible_discovery_tickers(config, overlay_dir=overlays)
    assert eligible == ("OPAL",)


def test_empty_watchlist_publishes_nothing(tmp_path: Path):
    overlays = tmp_path / "overlays"
    overlays.mkdir()
    (overlays / "OPAL.json").write_text("{}", encoding="utf-8")
    wl = Watchlist(entries=[])
    assert (
        resolve_publish_tickers(
            tickers=None,
            repo_root=tmp_path,
            overlay_dir=overlays,
            watchlist=wl,
        )
        == ()
    )


def test_watchlist_filters_period_and_worklist_roundtrip(tmp_path: Path):
    overlays = tmp_path / "overlays"
    overlays.mkdir()
    (overlays / "OPAL.json").write_text("{}", encoding="utf-8")
    (overlays / "STRW.json").write_text("{}", encoding="utf-8")
    call_at = datetime(2026, 8, 12, 16, 0, tzinfo=timezone.utc)
    cal_dir = tmp_path / "calendar"
    cal_dir.mkdir()
    (cal_dir / "OPAL.json").write_text(
        json.dumps([_quartr_earnings(ticker="OPAL", event_id="1", call_at=call_at)]),
        encoding="utf-8",
    )
    (cal_dir / "STRW.json").write_text(
        json.dumps(
            [
                _quartr_earnings(
                    ticker="STRW",
                    event_id="2",
                    event_type="q_2",
                    call_at=call_at,
                )
            ]
        ),
        encoding="utf-8",
    )
    wl = Watchlist()
    wl.add_entry("STRW", "FY2026-Q2")
    tickers = resolve_publish_tickers(
        tickers=None,
        repo_root=tmp_path,
        overlay_dir=overlays,
        watchlist=wl,
    )
    assert tickers == ("STRW",)
    gateway = MergedJsonDirGateway(cal_dir)
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    results = publish_calendar(
        gateway,
        tickers=("OPAL", "STRW"),
        events_dir=tmp_path / "events",
        horizon_days=30,
        now=now,
        watchlist=wl,
    )
    published = [r for r in results if r.skipped_reason is None]
    skipped = [r for r in results if r.skipped_reason == "not_on_watchlist"]
    assert len(published) == 1 and published[0].ticker == "STRW"
    assert any(r.ticker == "OPAL" for r in skipped)
    due = list_due_sweep_targets(
        gateway,
        tickers=("OPAL", "STRW"),
        within_hours=24 * 10,
        now=now,
        watchlist=wl,
    )
    assert [d.event_id for d in due] == ["2"]
    out = write_due_worklist(tmp_path / "due.json", due)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["due_sweep"][0]["ticker"] == "STRW"
