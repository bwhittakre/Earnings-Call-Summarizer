from __future__ import annotations

from pathlib import Path

from services.earnings_monitor.automation_watchlist import (
    Watchlist,
    load_watchlist,
    prune_event_manifests,
    save_watchlist_atomic,
)
from services.earnings_monitor.providers import EVENT_MANIFEST_SUFFIX


def test_add_remove_ticker_and_period(tmp_path: Path):
    path = tmp_path / "automation_watchlist.yaml"
    wl = Watchlist(entries=[], path=path)
    assert wl.add_entry("opal") is True
    assert wl.is_automated("OPAL", "FY2026-Q2")
    assert wl.add_entry("OPAL") is False
    assert wl.add_entry("STRW", "FY2026-Q2") is True
    assert wl.is_automated("STRW", "FY2026-Q2")
    assert not wl.is_automated("STRW", "FY2026-Q1")
    save_watchlist_atomic(path, wl)
    loaded = load_watchlist(path)
    assert loaded.iter_tickers() == ("OPAL", "STRW")
    assert loaded.remove_entry("STRW", "FY2026-Q2") is True
    assert not loaded.is_automated("STRW", "FY2026-Q2")
    assert loaded.remove_entry("OPAL") is True
    assert loaded.entries == []


def test_ticker_only_covers_quarters_and_dedupes_period_rows(tmp_path: Path):
    wl = Watchlist()
    assert wl.add_entry("OPAL", "FY2026-Q1")
    assert wl.add_entry("OPAL")  # upgrades to ticker-only, drops period row
    assert len(wl.entries) == 1
    assert wl.entries[0].period is None
    assert wl.add_entry("OPAL", "FY2026-Q2") is False


def test_prune_manifests(tmp_path: Path):
    events = tmp_path / "events"
    events.mkdir()
    keep = events / f"STRW-FY2026-Q2{EVENT_MANIFEST_SUFFIX}"
    drop = events / f"OPAL-FY2026-Q2{EVENT_MANIFEST_SUFFIX}"
    keep.write_text("{}", encoding="utf-8")
    drop.write_text("{}", encoding="utf-8")
    deleted = prune_event_manifests(events, ticker="OPAL")
    assert deleted == [str(drop)]
    assert keep.is_file()
    assert not drop.is_file()


def test_empty_file_and_missing_path(tmp_path: Path):
    missing = tmp_path / "missing.yaml"
    assert load_watchlist(missing).entries == []
    path = tmp_path / "empty.yaml"
    path.write_text("entries: []\n", encoding="utf-8")
    assert load_watchlist(path).entries == []
