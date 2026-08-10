from __future__ import annotations

import json
from pathlib import Path

from services.earnings_monitor.automation_watchlist import Watchlist
from services.earnings_monitor.calendar_publish import DueSweepTarget
from services.earnings_monitor.live_print_dispatch import run_dispatch


def _mcp_payload(*, event_id: str, text: str = "Hello from the call.") -> dict:
    return {
        "eventId": int(event_id) if event_id.isdigit() else event_id,
        "isLive": False,
        "lastTimestamp": 1.0,
        "paragraphs": [
            {
                "speakerName": "1",
                "text": text,
                "url": f"https://web.quartr.com/companies/1/events/{event_id}/overview",
            }
        ],
    }


def test_concurrent_dispatch_two_targets(tmp_path: Path):
    dumps = tmp_path / "dumps"
    inbox = tmp_path / "inbox"
    dumps.mkdir()
    (dumps / "101.json").write_text(
        json.dumps(_mcp_payload(event_id="101", text="OPAL content")),
        encoding="utf-8",
    )
    (dumps / "102.json").write_text(
        json.dumps(_mcp_payload(event_id="102", text="STRW content")),
        encoding="utf-8",
    )
    targets = [
        DueSweepTarget("101", "OPAL", "FY2026-Q2", call_at="2026-08-10T16:00:00Z"),
        DueSweepTarget("102", "STRW", "FY2026-Q2", call_at="2026-08-10T17:00:00Z"),
    ]
    wl = Watchlist()
    wl.add_entry("OPAL")
    wl.add_entry("STRW")
    results = run_dispatch(
        targets,
        dumps_dir=dumps,
        inbox=inbox,
        watchlist=wl,
        max_workers=2,
        once=True,
        force_final=True,
        wait_timeout_seconds=2.0,
        wait_poll_seconds=0.05,
    )
    assert len(results) == 2
    assert all(r.ok and r.skipped_reason is None for r in results)
    assert (inbox / "OPAL-FY2026-Q2.transcript.json").is_file()
    assert (inbox / "STRW-FY2026-Q2.transcript.json").is_file()


def test_dispatch_skips_missing_dump_and_watchlist(tmp_path: Path):
    dumps = tmp_path / "dumps"
    inbox = tmp_path / "inbox"
    dumps.mkdir()
    (dumps / "101.json").write_text(
        json.dumps(_mcp_payload(event_id="101")), encoding="utf-8"
    )
    targets = [
        DueSweepTarget("101", "OPAL", "FY2026-Q2", call_at=""),
        DueSweepTarget("102", "STRW", "FY2026-Q2", call_at=""),
        DueSweepTarget("103", "MSFT", "FY2026-Q2", call_at=""),
    ]
    wl = Watchlist()
    wl.add_entry("OPAL")
    wl.add_entry("STRW")  # dump missing
    results = run_dispatch(
        targets,
        dumps_dir=dumps,
        inbox=inbox,
        watchlist=wl,
        max_workers=2,
        once=True,
        force_final=True,
        wait_timeout_seconds=2.0,
        wait_poll_seconds=0.05,
    )
    by_id = {r.event_id: r for r in results}
    assert by_id["101"].ok and by_id["101"].skipped_reason is None
    assert by_id["102"].skipped_reason == "missing_dump"
    assert by_id["103"].skipped_reason == "not_on_watchlist"
    assert (inbox / "OPAL-FY2026-Q2.transcript.json").is_file()
    assert not (inbox / "STRW-FY2026-Q2.transcript.json").is_file()
