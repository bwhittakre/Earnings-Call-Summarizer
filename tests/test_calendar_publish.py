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
    monitored_universe_tickers,
    registry_tickers,
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


def _eligibility_config(tmp_path: Path, **overrides) -> MonitorConfig:
    overlays = tmp_path / "Structured Narrative" / "config" / "company_overlays"
    overlays.mkdir(parents=True, exist_ok=True)
    (overlays / "OPAL.json").write_text("{}", encoding="utf-8")
    (overlays / "STRW.json").write_text("{}", encoding="utf-8")
    sector = tmp_path / "config" / "sectors"
    sector.mkdir(parents=True, exist_ok=True)
    (sector / "xlk_tech.txt").write_text("OPAL\nMSFT\n", encoding="utf-8")
    return MonitorConfig(
        repo_root=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        inbox_path=tmp_path / "inbox",
        tickers=("MSFT", "AAPL"),
        research_sector="xlk_tech",
        **overrides,
    )


def test_eligible_discovery_defaults_to_every_onboarded_company(tmp_path: Path):
    """STRW is onboarded but off the research book, and must still be watched.

    This is the healthcare case: names deliberately kept out of the Rank IC
    comparison pool were dropped from discovery too.
    """
    config = _eligibility_config(tmp_path)
    overlays = tmp_path / "Structured Narrative" / "config" / "company_overlays"
    assert list_overlay_tickers(overlays) == frozenset({"OPAL", "STRW"})
    assert eligible_discovery_tickers(config, overlay_dir=overlays) == ("OPAL", "STRW")
    assert monitored_universe_tickers(config, overlay_dir=overlays) == ("OPAL", "STRW")


def test_excluded_tickers_drop_out_without_deleting_the_overlay(tmp_path: Path):
    config = _eligibility_config(tmp_path, monitor_excluded_tickers=("STRW",))
    overlays = tmp_path / "Structured Narrative" / "config" / "company_overlays"
    assert (overlays / "STRW.json").exists()
    assert eligible_discovery_tickers(config, overlay_dir=overlays) == ("OPAL",)


def test_registry_only_companies_are_watched_without_an_overlay(tmp_path: Path):
    """The original tech book has no overlay files and must still be watched."""
    import sys

    sn = tmp_path / "Structured Narrative"
    sn.mkdir(parents=True, exist_ok=True)
    (sn / "company_config.py").write_text(
        "COMPANIES = {'MSFT': object(), 'AAPL': object()}\n", encoding="utf-8"
    )
    config = _eligibility_config(tmp_path)
    overlays = tmp_path / "Structured Narrative" / "config" / "company_overlays"
    saved = sys.modules.pop("company_config", None)
    try:
        assert registry_tickers(tmp_path) == frozenset({"AAPL", "MSFT"})
        assert eligible_discovery_tickers(config, overlay_dir=overlays) == (
            "AAPL",
            "MSFT",
            "OPAL",
            "STRW",
        )
    finally:
        sys.modules.pop("company_config", None)
        if saved is not None:
            sys.modules["company_config"] = saved
        if str(sn) in sys.path:
            sys.path.remove(str(sn))


def test_registry_from_another_repo_is_not_inherited(tmp_path: Path):
    """A cached company_config from elsewhere must not leak into this repo."""
    assert registry_tickers(tmp_path / "no-such-repo") == frozenset()


def test_publish_covers_registry_companies_that_have_no_overlay(tmp_path: Path):
    """Publish gating must match discovery gating.

    ADSK is watched via the in-code registry and has no overlay file. Gating
    publish on overlays alone would silently write no manifest for it, so it
    would stay undiscoverable no matter what the calendar sweep found.
    """
    import sys

    sn = tmp_path / "Structured Narrative"
    sn.mkdir(parents=True, exist_ok=True)
    (sn / "company_config.py").write_text(
        "COMPANIES = {'ADSK': object()}\n", encoding="utf-8"
    )
    overlays = sn / "config" / "company_overlays"
    overlays.mkdir(parents=True, exist_ok=True)
    (overlays / "OPAL.json").write_text("{}", encoding="utf-8")
    wl = Watchlist(entries=[])
    wl.add_entry("ADSK")
    wl.add_entry("OPAL")
    saved = sys.modules.pop("company_config", None)
    try:
        assert not (overlays / "ADSK.json").exists()
        assert resolve_publish_tickers(
            tickers=None,
            repo_root=tmp_path,
            overlay_dir=overlays,
            watchlist=wl,
        ) == ("ADSK", "OPAL")
    finally:
        sys.modules.pop("company_config", None)
        if saved is not None:
            sys.modules["company_config"] = saved
        if str(sn) in sys.path:
            sys.path.remove(str(sn))


def test_sync_tracks_the_universe_and_keeps_hand_pinned_quarters():
    """Sync owns ticker-only membership; explicit quarters are an operator's."""
    from services.earnings_monitor.automation_watchlist import sync_entries

    wl = Watchlist(entries=[])
    wl.add_entry("OPAL")  # onboarded, stays
    wl.add_entry("GONE")  # no longer onboarded, dropped
    wl.add_entry("STRW", "FY2026-Q2")  # hand-pinned quarter, untouched
    added, removed = sync_entries(wl, ["OPAL", "ADSK"])

    assert added == ["ADSK"]
    assert removed == ["GONE"]
    assert wl.is_automated("ADSK")
    assert not wl.is_automated("GONE")
    # The pin survives even though STRW is not in the synced universe.
    assert wl.is_automated("STRW", "FY2026-Q2")
    assert not wl.is_automated("STRW", "FY2026-Q3")


def test_sync_is_idempotent():
    from services.earnings_monitor.automation_watchlist import sync_entries

    wl = Watchlist(entries=[])
    sync_entries(wl, ["OPAL", "ADSK"])
    added, removed = sync_entries(wl, ["OPAL", "ADSK"])
    assert (added, removed) == ([], [])


def test_book_mode_restores_the_legacy_intersection(tmp_path: Path):
    config = _eligibility_config(tmp_path, monitor_universe_mode="book")
    overlays = tmp_path / "Structured Narrative" / "config" / "company_overlays"
    # Book = env tickers ∪ sector → MSFT, AAPL, OPAL; ∩ overlays → OPAL only
    # (MSFT has no overlay; STRW overlay but not in book).
    assert eligible_discovery_tickers(config, overlay_dir=overlays) == ("OPAL",)


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

def test_null_fiscal_year_falls_back_to_the_title_year():
    """Quartr returns fiscalYear=None for BMY/LLY/MRK/IBM; the title has it.

    Without the fallback these rows yield no fiscal period and the company is
    dropped in silence -- it simply never gets armed.
    """
    from services.earnings_monitor.calendar_publish import quartr_row_to_manifest

    row = {
        "id": 733001,
        "ticker": "BMY",
        "companyId": 1234,
        "title": "Q3 2026",
        "eventType": "q_3",
        "parentEventType": "earnings_call",
        "fiscalYear": None,
        "contentDates": [
            {"contentType": "report", "date": "2026-10-29T12:00:00.000Z"},
            {"contentType": "audio", "date": "2026-10-29T12:00:00.000Z"},
        ],
    }
    manifest = quartr_row_to_manifest(row)
    assert manifest is not None
    assert manifest["fiscal_period"] == "FY2026-Q3"


def test_explicit_fiscal_year_still_wins_over_the_title():
    from services.earnings_monitor.providers import _fiscal_period

    row = {"eventType": "q_3", "title": "Q3 2026", "fiscalYear": 2027}
    assert _fiscal_period(row) == "FY2027-Q3"


def test_post_earnings_session_does_not_displace_the_call():
    """MU FY2026-Q4 returns the call at 20:30Z and a 'Post' event at 22:00Z.

    Both share a manifest filename and the monitor's unique (ticker, period)
    key, so without a rule the winner is whichever was written last.
    """
    from services.earnings_monitor.calendar_publish import dedupe_by_period

    call = {
        "ticker": "MU",
        "fiscal_period": "FY2026-Q4",
        "provider_event_id": "699706",
        "call_at": "2026-09-30T20:30:00Z",
    }
    post = {
        "ticker": "MU",
        "fiscal_period": "FY2026-Q4",
        "provider_event_id": "742832",
        "call_at": "2026-09-30T22:00:00Z",
    }
    for ordering in ([call, post], [post, call]):
        kept = dedupe_by_period(ordering)
        assert len(kept) == 1
        assert kept[0]["provider_event_id"] == "699706"


def test_dedupe_keeps_distinct_quarters():
    """ADBE and AVGO legitimately have two upcoming quarters in the window."""
    from services.earnings_monitor.calendar_publish import dedupe_by_period

    rows = [
        {"ticker": "ADBE", "fiscal_period": "FY2026-Q3", "provider_event_id": "1",
         "call_at": "2026-09-11T21:00:00Z"},
        {"ticker": "ADBE", "fiscal_period": "FY2026-Q4", "provider_event_id": "2",
         "call_at": "2026-12-11T21:00:00Z"},
    ]
    assert len(dedupe_by_period(rows)) == 2


def test_estimated_report_after_the_call_is_clamped_not_dropped():
    """Quartr estimates report and call independently; they drift apart.

    GILD FY2026-Q3 came back with the call on Oct 29 and the report on Nov 6.
    Roz requires call_at >= report_at, so an unclamped row raises and (before
    the guard) aborted the entire sweep.
    """
    from services.earnings_monitor.calendar_publish import quartr_row_to_manifest

    row = {
        "id": 723977,
        "ticker": "GILD",
        "companyId": 999,
        "title": "Q3 2026",
        "eventType": "q_3",
        "parentEventType": "earnings_call",
        "contentDates": [
            {"contentType": "audio", "date": "2026-10-29T20:30:00.000Z",
             "contentStatus": "estimated"},
            {"contentType": "report", "date": "2026-11-06T21:00:00.000Z",
             "contentStatus": "estimated"},
        ],
    }
    manifest = quartr_row_to_manifest(row)
    assert manifest is not None
    assert manifest["call_at"] == "2026-10-29T20:30:00Z"
    assert manifest["report_at"] == manifest["call_at"]


def test_normal_ordering_is_left_alone():
    from services.earnings_monitor.calendar_publish import quartr_row_to_manifest

    row = {
        "id": 1, "ticker": "AAPL", "companyId": 9, "title": "Q4 2026",
        "eventType": "q_4", "parentEventType": "earnings_call",
        "contentDates": [
            {"contentType": "report", "date": "2026-10-30T20:30:00.000Z"},
            {"contentType": "audio", "date": "2026-10-30T21:00:00.000Z"},
        ],
    }
    m = quartr_row_to_manifest(row)
    assert m["report_at"] == "2026-10-30T20:30:00Z"
    assert m["call_at"] == "2026-10-30T21:00:00Z"


def test_one_unwritable_manifest_does_not_abort_the_whole_sweep(tmp_path):
    """A 45-company sweep must not be ended by a single malformed row."""
    from services.earnings_monitor.calendar_publish import publish_calendar

    good = {
        "id": 2, "ticker": "MSFT", "companyId": 9, "title": "Q1 2027",
        "eventType": "q_1", "parentEventType": "earnings_call",
        "contentDates": [
            {"contentType": "report", "date": "2026-09-20T20:30:00.000Z"},
            {"contentType": "audio", "date": "2026-09-20T21:00:00.000Z"},
        ],
    }

    class _Gateway:
        def list_events(self, *, ticker):
            return [good] if ticker == "MSFT" else []

    class _Boom(dict):
        pass

    import services.earnings_monitor.calendar_publish as cp

    original = cp.write_event_manifest_atomic
    calls = {"n": 0}

    def flaky(path, manifest):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("call_at cannot precede report_at")
        return original(path, manifest)

    cp.write_event_manifest_atomic = flaky
    try:
        results = publish_calendar(
            _Gateway(),
            tickers=["MSFT", "MSFT"],
            events_dir=tmp_path,
            horizon_days=400,
            now=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    finally:
        cp.write_event_manifest_atomic = original

    reasons = [r.skipped_reason for r in results]
    assert any(r and r.startswith("invalid_manifest") for r in reasons)
    # The second ticker still published despite the first blowing up.
    assert any(r.path for r in results)


def _row(call_iso, event_id="900"):
    return {
        "id": event_id, "ticker": "AAPL", "companyId": 9, "title": "Q4 2026",
        "eventType": "q_4", "parentEventType": "earnings_call",
        "contentDates": [
            {"contentType": "report", "date": call_iso},
            {"contentType": "audio", "date": call_iso},
        ],
    }


class _OneRow:
    def __init__(self, row):
        self.row = row

    def list_events(self, *, ticker):
        return [self.row]


def test_publish_reports_a_moved_call_instead_of_silently_overwriting(tmp_path):
    """Re-verification is worthless if the answer is invisible."""
    from services.earnings_monitor.calendar_publish import publish_calendar

    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    window = dict(tickers=["AAPL"], events_dir=tmp_path, horizon_days=200, now=now)

    first = publish_calendar(_OneRow(_row("2026-10-30T21:00:00.000Z")), **window)
    assert first[0].previous_call_at is None
    assert not first[0].rescheduled

    second = publish_calendar(_OneRow(_row("2026-11-04T21:00:00.000Z")), **window)
    assert second[0].rescheduled
    assert second[0].previous_call_at == "2026-10-30T21:00:00Z"
    assert second[0].call_at == "2026-11-04T21:00:00Z"


def test_unchanged_schedule_is_not_reported_as_moved(tmp_path):
    from services.earnings_monitor.calendar_publish import publish_calendar

    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    window = dict(tickers=["AAPL"], events_dir=tmp_path, horizon_days=200, now=now)
    publish_calendar(_OneRow(_row("2026-10-30T21:00:00.000Z")), **window)
    again = publish_calendar(_OneRow(_row("2026-10-30T21:00:00.000Z")), **window)
    assert not again[0].rescheduled


def test_a_corrupt_existing_manifest_does_not_break_the_sweep(tmp_path):
    """Change detection is reporting; it must never fail a publish."""
    from services.earnings_monitor.calendar_publish import (
        manifest_path_for,
        publish_calendar,
        published_call_at,
    )

    path = manifest_path_for(tmp_path, "AAPL", "FY2026-Q4")
    path.write_text("{not json", encoding="utf-8")
    assert published_call_at(path) is None

    results = publish_calendar(
        _OneRow(_row("2026-10-30T21:00:00.000Z")),
        tickers=["AAPL"],
        events_dir=tmp_path,
        horizon_days=200,
        now=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    assert results[0].path and not results[0].rescheduled
