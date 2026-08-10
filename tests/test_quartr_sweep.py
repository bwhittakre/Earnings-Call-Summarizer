from __future__ import annotations

import json
from pathlib import Path

from services.earnings_monitor.quartr_sweep import (
    CallableGateway,
    JsonDumpGateway,
    SweepTarget,
    mcp_payload_to_bundle,
    run_sweep_loop,
    write_sweep_bundle,
)


def _mcp_payload(*, event_id: str = "692045", is_live: bool = True, text: str = "Hello") -> dict:
    return {
        "eventId": int(event_id) if event_id.isdigit() else event_id,
        "isLive": is_live,
        "lastTimestamp": 123.4,
        "paragraphs": [
            {
                "speakerName": "1",
                "text": text,
                "url": f"https://web.quartr.com/companies/1/events/{event_id}/overview",
            },
            {"speakerName": "2", "text": "More content from management."},
        ],
    }


def test_mcp_payload_to_bundle_live_and_final_ids():
    live = mcp_payload_to_bundle(
        _mcp_payload(is_live=True),
        event_id="692045",
        ticker="strw",
        fiscal_period="fy2026-q2",
    )
    assert live["status"] == "live"
    assert live["provider_event_id"] == "692045"
    assert live["provider_document_id"] == "quartr-live-692045-123.4"
    assert live["ticker"] == "STRW"
    assert live["fiscal_period"] == "FY2026-Q2"
    assert live["speaker_text"][0]["speaker"] == "Speaker 1"

    final = mcp_payload_to_bundle(
        _mcp_payload(is_live=True),
        event_id="692045",
        ticker="STRW",
        fiscal_period="FY2026-Q2",
        force_final=True,
        speaker_map={"1": "Operator", "2": "CEO"},
    )
    assert final["status"] == "final"
    assert final["provider_document_id"] == "quartr-final-692045"
    assert final["speaker_text"][0]["speaker"] == "Operator"
    assert final["speaker_text"][1]["speaker"] == "CEO"


def test_json_dump_gateway_writes_atomic_bundle(tmp_path: Path):
    dump = tmp_path / "mcp.json"
    dump.write_text(json.dumps(_mcp_payload(is_live=True)), encoding="utf-8")
    inbox = tmp_path / "inbox"
    target = SweepTarget(
        event_id="692045",
        ticker="STRW",
        fiscal_period="FY2026-Q2",
        inbox=inbox,
    )
    result = write_sweep_bundle(JsonDumpGateway(dump), target)
    assert result["status"] == "live"
    assert result["provider_event_id"] == "692045"
    out = inbox / "STRW-FY2026-Q2.transcript.json"
    assert out.is_file()
    bundle = json.loads(out.read_text(encoding="utf-8"))
    assert bundle["schema_version"] == 1
    assert bundle["status"] == "live"
    assert len(bundle["speaker_text"]) == 2


def test_loop_finalizes_when_not_live(tmp_path: Path):
    state = {"live": True}

    def fetch(event_id: str) -> dict:
        assert event_id == "99"
        payload = _mcp_payload(event_id="99", is_live=state["live"], text="Body")
        state["live"] = False
        return payload

    inbox = tmp_path / "inbox"
    target = SweepTarget(
        event_id="99",
        ticker="AAPL",
        fiscal_period="FY2026-Q3",
        inbox=inbox,
    )
    result = run_sweep_loop(
        CallableGateway(fetch),
        target,
        interval_seconds=0.01,
        max_minutes=1,
    )
    assert result["status"] == "final"
    assert result["provider_document_id"] == "quartr-final-99"
    bundle = json.loads(
        (inbox / "AAPL-FY2026-Q3.transcript.json").read_text(encoding="utf-8")
    )
    assert bundle["status"] == "final"
    assert bundle["provider_event_id"] == "99"
