from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.earnings_monitor.calendar_publish import DueSweepTarget
from services.earnings_monitor.dashboard.data import DashboardData
from services.earnings_monitor.live_print_dispatch import run_dispatch
from services.earnings_monitor.ops_health import (
    book_ranks_summary_alerts,
    event_is_stuck,
    host_health_alerts,
    research_freshness_alerts,
    write_host_health,
)

UTC = timezone.utc


def test_pre_call_wait_not_stuck_before_call():
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    event = {
        "state": "awaiting_call",
        "updated_at": (now - timedelta(hours=5)).isoformat(),
        "call_at": (now + timedelta(hours=2)).isoformat(),
    }
    stuck, _ = event_is_stuck(event, now=now, stuck_after_seconds=7200)
    assert stuck is False


def test_pre_call_stuck_after_call_plus_grace():
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    event = {
        "state": "awaiting_call",
        "updated_at": (now - timedelta(hours=1)).isoformat(),
        "call_at": (now - timedelta(hours=2)).isoformat(),
    }
    stuck, detail = event_is_stuck(
        event, now=now, stuck_after_seconds=7200, grace_seconds=1800
    )
    assert stuck is True
    assert detail and "schedule+grace" in detail


def test_running_state_uses_updated_at_age():
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    event = {
        "state": "quant_running",
        "updated_at": (now - timedelta(hours=3)).isoformat(),
        "call_at": (now - timedelta(hours=1)).isoformat(),
    }
    stuck, _ = event_is_stuck(event, now=now, stuck_after_seconds=7200)
    assert stuck is True


def test_dashboard_operational_alerts_respect_pre_call_sla():
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    data = DashboardData.from_records(
        [],
        operational_events=[
            {
                "provider_event_id": "event-wait",
                "ticker": "MSFT",
                "state": "awaiting_call",
                "call_at": (now + timedelta(hours=3)).isoformat(),
                "updated_at": (now - timedelta(hours=5)).isoformat(),
            },
            {
                "provider_event_id": "event-run",
                "ticker": "MU",
                "state": "quant_running",
                "call_at": (now - timedelta(hours=1)).isoformat(),
                "updated_at": (now - timedelta(hours=3)).isoformat(),
            },
        ],
        poll_cycles=[
            {
                "started_at": now.isoformat(),
                "finished_at": now.isoformat(),
            }
        ],
    )
    alerts = data.operational_alerts(now=now, stuck_after_seconds=7200)
    stuck_ids = {
        a["provider_event_id"] for a in alerts if a["kind"] == "stuck_event"
    }
    assert "event-wait" not in stuck_ids
    assert "event-run" in stuck_ids


def test_host_health_alerts_missing_dump_and_stale(tmp_path: Path):
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    path = tmp_path / "last_run.json"
    write_host_health(
        path,
        job="live",
        ok=False,
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=2),
        failures=[
            {
                "event_id": "e1",
                "ticker": "OPAL",
                "skipped_reason": "missing_dump",
                "error": "missing_dump",
            }
        ],
    )
    health = json.loads(path.read_text(encoding="utf-8"))
    alerts = host_health_alerts(health, now=now, stale_after_seconds=1800)
    kinds = {a["kind"] for a in alerts}
    assert "host_missing_dump" in kinds
    assert "host_feed_stale" in kinds


def test_research_and_ranks_alert_helpers():
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    research = research_freshness_alerts(
        dirty={"marked_at": (now - timedelta(hours=2)).isoformat(), "reason": "post_call"},
        last_regen={"ok": False, "finished_at": now.isoformat()},
        now=now,
        debounce_seconds=60,
        idle_seconds=30,
        universe_stale_message="Rank IC missing AAPL",
    )
    kinds = {a["kind"] for a in research}
    assert "research_book_stale" in kinds
    assert "research_universe_stale" in kinds

    ranks = book_ranks_summary_alerts(
        {
            "skipped_reason": "below_min_names",
            "n_peers": 1,
            "period_bucket": "2026-Q2",
            "built_at": now.isoformat(),
        },
        now=now,
    )
    assert ranks[0]["kind"] == "book_ranks_thin_peers"

    overdue = book_ranks_summary_alerts(
        {
            "skipped_reason": "awaiting_investable_asof",
            "pending": True,
            "as_of_date": (now - timedelta(days=1)).date().isoformat(),
            "built_at": now.isoformat(),
        },
        now=now,
        asof_grace_seconds=3600,
    )
    assert any(a["kind"] == "book_ranks_asof_overdue" for a in overdue)


def test_near_call_missing_dump_is_hard_fail(tmp_path: Path):
    dumps = tmp_path / "dumps"
    inbox = tmp_path / "inbox"
    dumps.mkdir()
    now = datetime(2026, 8, 10, 16, tzinfo=UTC)
    targets = [
        DueSweepTarget(
            "102",
            "STRW",
            "FY2026-Q2",
            call_at=now.isoformat().replace("+00:00", "Z"),
        ),
    ]
    results = run_dispatch(
        targets,
        dumps_dir=dumps,
        inbox=inbox,
        watchlist=None,
        max_workers=1,
        once=True,
        force_final=True,
        require_dump=None,
        max_dump_age_minutes=None,
        now=now,
    )
    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].skipped_reason == "missing_dump"
