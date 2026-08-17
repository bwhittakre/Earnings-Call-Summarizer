from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.earnings_monitor.live_print_loop import (
    run_live_print_loop,
    wait_for_fresh_dump,
)


def _mcp_payload(*, event_id: str = "665958", is_live: bool = False) -> dict:
    return {
        "eventId": int(event_id),
        "isLive": is_live,
        "lastTimestamp": 10.0,
        "paragraphs": [
            {
                "speakerName": "1",
                "text": "Welcome to the call.",
                "url": f"https://web.quartr.com/companies/1/events/{event_id}/overview",
            }
        ],
    }


def test_wait_for_fresh_dump_accepts_existing(tmp_path: Path):
    dump = tmp_path / "t.json"
    dump.write_text("{}", encoding="utf-8")
    result = wait_for_fresh_dump(dump, timeout_seconds=1.0, poll_seconds=0.05)
    assert Path(result.path) == dump
    assert result.mtime_ns > 0


def test_wait_for_fresh_dump_timeout(tmp_path: Path):
    missing = tmp_path / "missing.json"
    with pytest.raises(TimeoutError):
        wait_for_fresh_dump(missing, timeout_seconds=0.2, poll_seconds=0.05)


def test_run_live_print_loop_once(tmp_path: Path):
    dump = tmp_path / "mcp.json"
    dump.write_text(json.dumps(_mcp_payload(is_live=True)), encoding="utf-8")
    inbox = tmp_path / "inbox"
    result = run_live_print_loop(
        event_id="665958",
        ticker="OPAL",
        fiscal_period="FY2026-Q2",
        dump_path=dump,
        inbox=inbox,
        once=True,
        force_final=True,
        wait_timeout_seconds=2.0,
        wait_poll_seconds=0.05,
    )
    assert result["sweep"]["status"] == "final"
    out = inbox / "OPAL-FY2026-Q2.transcript.json"
    assert out.is_file()
