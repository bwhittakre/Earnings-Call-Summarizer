from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from services.earnings_monitor.config import MonitorConfig
from services.earnings_monitor.decision_output import DecisionOutputAssembler
from services.earnings_monitor.models import EarningsEvent
from services.earnings_monitor.notifications import SMTPMailSender, TwoEmailNotifier
from services.earnings_monitor.state import OperationalState
from services.earnings_monitor.storage import write_company_quarter_dataset


def _event() -> EarningsEvent:
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    return EarningsEvent(
        "event-4",
        "MU",
        "FY2026-Q3",
        report_at=now,
        call_at=now + timedelta(hours=1),
    )


def _scorecard_fixture(tmp_path: Path) -> DecisionOutputAssembler:
    dataset = tmp_path / "company_quarters.parquet"
    write_company_quarter_dataset(
        dataset,
        [
            {
                "ticker": "MU",
                "fiscal_period": "FY2026-Q3",
                "dimension": "Demand",
                "quant_value": 18.5,
                "quant_z_pit": 1.4,
                "llm_level": 2,
                "change_magnitude": 1,
                "narrative_quant_gap": 0.6,
                "any_quant_divergence": True,
                "surprise_rationale": "Management described stronger data-center demand.",
                "surprise_evidence_supported_pct": 1.0,
                "as_of_date": "2026-07-31T11:45:00Z",
                "history_incomplete": False,
            },
            {
                "ticker": "MU",
                "fiscal_period": "FY2026-Q3",
                "dimension": "Margins",
                "quant_z_pit": -0.3,
                "llm_level": 0,
                "change_magnitude": -1,
                "narrative_quant_gap": -0.7,
                "any_quant_divergence": False,
                "history_incomplete": False,
            },
        ],
        prefer_parquet=False,
    )
    registry = tmp_path / "output" / "MU" / "json" / "quarter_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        """
        {"scored_quarters":{"FY2026-Q3":{
          "dimensions_scored_at":"2026-07-31T12:00:00Z",
          "delta_scored_at":"2026-07-31T12:01:00Z",
          "surprise_scored_at":"2026-07-31T12:02:00Z",
          "novelty_scored_at":"2026-07-31T12:03:00Z"
        }}}
        """,
        encoding="utf-8",
    )
    return DecisionOutputAssembler(dataset, tmp_path / "output")


def test_decision_output_assembles_dimensions_divergence_and_evidence(tmp_path: Path) -> None:
    output = _scorecard_fixture(tmp_path).assemble(_event())

    assert output["as_of"] == "2026-07-31T11:45:00Z"
    assert output["completion"]["complete"] is True
    assert output["dimensions"][0]["dimension"] == "Demand"
    assert output["dimensions"][0]["quant_z"] == 1.4
    assert output["dimensions"][0]["evidence"].startswith("Management")
    assert [row["dimension"] for row in output["divergences"]] == ["Demand"]


def test_decision_output_reports_missing_dataset_without_raising(tmp_path: Path) -> None:
    output = DecisionOutputAssembler(
        tmp_path / "missing.parquet", tmp_path / "missing-output"
    ).assemble(_event())

    assert output["completion"]["complete"] is False
    assert "dataset_unavailable:FileNotFoundError" in output["completion"]["issues"]
    assert output["dimensions"] == []


def test_decision_output_surfaces_quant_preface_rows_without_narrative(
    tmp_path: Path,
) -> None:
    """Email 1 / quant preface: quant_z present, narrative null — still emit rows."""
    dataset = tmp_path / "company_quarters.parquet"
    write_company_quarter_dataset(
        dataset,
        [
            {
                "ticker": "MU",
                "fiscal_period": "FY2026-Q3",
                "dimension": "Demand",
                "quant_z_pit": 1.25,
                "quant_z": 1.25,
                "llm_level": None,
                "change_magnitude": None,
                "as_of_date": "2026-07-31T11:45:00Z",
                "history_incomplete": False,
            },
            {
                "ticker": "MU",
                "fiscal_period": "FY2026-Q3",
                "dimension": "Margins",
                "quant_z": -0.4,
                "llm_level": None,
                "change_magnitude": None,
                "history_incomplete": False,
            },
        ],
        prefer_parquet=False,
    )
    assembler = DecisionOutputAssembler(dataset, tmp_path / "output")
    output = assembler.assemble(_event())

    assert len(output["dimensions"]) == 2
    by_dim = {row["dimension"]: row for row in output["dimensions"]}
    assert by_dim["Demand"]["quant_z"] == 1.25
    assert by_dim["Demand"]["measure"] is None
    assert by_dim["Demand"]["narrative_level"] is None
    assert by_dim["Margins"]["quant_z"] == -0.4

    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()

    class Sender:
        def __init__(self) -> None:
            self.messages = []

        def send(self, message) -> None:
            self.messages.append(message)

    sender = Sender()
    config = MonitorConfig(
        repo_root=tmp_path,
        database_path=tmp_path / "monitor.sqlite3",
        inbox_path=tmp_path / "inbox",
        dashboard_url="https://roz.example.test",
    )
    notifier = TwoEmailNotifier(
        state=state,
        sender=sender,
        sender_address="roz@example.test",
        recipients=("investor@example.test",),
        config=config,
        assembler=assembler,
    )
    assert notifier.pre_call_quant(_event(), detail="quant preface")
    html = sender.messages[0].get_body(preferencelist=("html",)).get_content()
    assert "No measures available" not in html
    assert "Demand" in html
    assert "1.25" in html


def test_multipart_templates_and_recovery_are_idempotent(tmp_path: Path) -> None:
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()

    class Sender:
        def __init__(self) -> None:
            self.messages = []

        def send(self, message) -> None:
            self.messages.append(message)

    sender = Sender()
    config = MonitorConfig(
        repo_root=tmp_path,
        database_path=tmp_path / "monitor.sqlite3",
        inbox_path=tmp_path / "inbox",
        dashboard_url="https://roz.example.test",
        artifact_public_base_url="https://artifacts.example.test",
    )
    notifier = TwoEmailNotifier(
        state=state,
        sender=sender,
        sender_address="roz@example.test",
        recipients=("investor@example.test",),
        config=config,
        assembler=_scorecard_fixture(tmp_path),
    )

    assert notifier.pre_call_quant(_event(), detail="fresh as of 11:45Z")
    assert not notifier.pre_call_quant(_event())
    assert notifier.stall_failure(
        _event(), stage="post_call", attempts=3, detail="model timeout"
    )
    assert not notifier.stall_failure(
        _event(), stage="post_call", attempts=4, detail="same incident"
    )
    assert notifier.final_combined(_event(), success=True, detail="retry completed")
    assert not notifier.final_combined(_event(), success=True)

    assert len(sender.messages) == 3
    assert all(message.is_multipart() for message in sender.messages)
    assert all(
        {"text/plain", "text/html"}.issubset(
            {part.get_content_type() for part in message.walk()}
        )
        for message in sender.messages
    )
    assert "Measures and z-scores" in sender.messages[0].get_body(
        preferencelist=("plain",)
    ).get_content()
    failure_text = sender.messages[1].get_body(preferencelist=("plain",)).get_content()
    assert "Stage: post_call" in failure_text
    assert "Attempts: 3" in failure_text
    assert "recovery successful" in sender.messages[2]["Subject"]
    final_text = sender.messages[2].get_body(preferencelist=("plain",)).get_content()
    assert "DIVERGENCE" in final_text
    assert "https://artifacts.example.test/events/MU/FY2026-Q3" in final_text


def test_operational_alert_does_not_repeat_per_cycle(tmp_path: Path) -> None:
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()

    class Sender:
        messages = []

        def send(self, message) -> None:
            self.messages.append(message)

    sender = Sender()
    notifier = TwoEmailNotifier(
        state=state,
        sender=sender,
        sender_address="monitor@example.test",
        recipients=("ops@example.test",),
    )
    alert = {
        "kind": "repeated_failure",
        "provider_event_id": "event-4",
        "state": "post_call_queued",
        "failures": 3,
        "occurrence": "failure-streak-1",
        "detail": "3 failed workflow attempts",
    }

    assert notifier.operational_alert(alert)
    assert not notifier.operational_alert({**alert, "failures": 4})
    assert notifier.operational_alert(
        {**alert, "occurrence": "failure-streak-2", "failures": 2}
    )
    assert len(sender.messages) == 2


def test_notification_claim_migrates_old_sent_at_not_null_schema(
    tmp_path: Path,
) -> None:
    database = tmp_path / "monitor.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE notifications ("
        "notification_key TEXT PRIMARY KEY, sent_at TEXT NOT NULL)"
    )
    connection.commit()
    connection.close()

    state = OperationalState(database)
    state.initialize()

    assert state.claim_notification("new-key")
    assert state.mark_notification_sent("new-key")
    assert state.notification_sent("new-key")


def test_microsoft365_smtp_uses_port_587_starttls_and_login(
    tmp_path: Path, monkeypatch
) -> None:
    config = MonitorConfig.from_env(
        {
            "EARNINGS_MONITOR_SMTP_MODE": "microsoft365",
            "EARNINGS_MONITOR_SMTP_USERNAME": "roz@example.test",
            "EARNINGS_MONITOR_SMTP_PASSWORD": "test-secret",
            "EARNINGS_MONITOR_SMTP_TO": "investor@example.test",
        },
        repo_root=tmp_path,
    )
    calls: list[tuple] = []
    tls_context = object()

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def starttls(self, *, context):
            calls.append(("starttls", context))

        def ehlo(self):
            calls.append(("ehlo",))

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, message):
            calls.append(("send", message["To"]))

    monkeypatch.setattr(
        "services.earnings_monitor.notifications.smtplib.SMTP", FakeSMTP
    )
    monkeypatch.setattr(
        "services.earnings_monitor.notifications.ssl.create_default_context",
        lambda: tls_context,
    )
    from email.message import EmailMessage

    message = EmailMessage()
    message["To"] = "investor@example.test"
    SMTPMailSender(config).send(message)

    assert config.smtp_setup_issues == ()
    assert calls[0] == ("connect", "smtp.office365.com", 587, 30)
    assert ("starttls", tls_context) in calls
    assert ("login", "roz@example.test", "test-secret") in calls
