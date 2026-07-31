"""Idempotent multipart SMTP notifications for monitor milestones and alerts."""

from __future__ import annotations

import hashlib
import json
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
from typing import Any, Mapping, Protocol

from .config import MonitorConfig
from .decision_output import DecisionOutputAssembler
from .models import EarningsEvent
from .state import OperationalState


class MailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class SMTPMailSender:
    def __init__(self, config: MonitorConfig):
        self.config = config

    def send(self, message: EmailMessage) -> None:
        if not self.config.smtp_host:
            raise RuntimeError("SMTP host is not configured")
        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as client:
            if self.config.smtp_starttls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if self.config.smtp_username:
                client.login(self.config.smtp_username, self.config.smtp_password or "")
            client.send_message(message)


@dataclass(frozen=True)
class NotificationContent:
    subject: str
    text: str
    html: str


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _html_page(title: str, sections: list[tuple[str, str]]) -> str:
    content = "".join(
        f"<h2>{escape(heading)}</h2><div>{body}</div>" for heading, body in sections
    )
    return (
        "<!doctype html><html><body style=\"font-family:Segoe UI,Arial,sans-serif;"
        "color:#172033;line-height:1.45\">"
        f"<h1 style=\"font-size:22px\">{escape(title)}</h1>{content}</body></html>"
    )


class TwoEmailNotifier:
    """Sends quant-ready before the call and one final combined outcome."""

    def __init__(
        self,
        *,
        state: OperationalState,
        sender: MailSender,
        sender_address: str,
        recipients: tuple[str, ...],
        config: MonitorConfig | None = None,
        assembler: DecisionOutputAssembler | None = None,
    ):
        self.state = state
        self.sender = sender
        self.sender_address = sender_address
        self.recipients = recipients
        self.config = config
        self.assembler = assembler or (
            DecisionOutputAssembler(config.dataset_path, config.history_source_path)
            if config
            else None
        )

    def _send_once(self, key: str, content: NotificationContent) -> bool:
        if not self.state.claim_notification(key):
            return False
        message = EmailMessage()
        message["From"] = self.sender_address
        message["To"] = ", ".join(self.recipients)
        message["Subject"] = content.subject
        message.set_content(content.text)
        message.add_alternative(content.html, subtype="html")
        try:
            self.sender.send(message)
        except Exception:
            self.state.release_notification(key)
            raise
        self.state.mark_notification_sent(key)
        return True

    def pre_call_quant(self, event: EarningsEvent, *, detail: str = "") -> bool:
        scorecard = self._scorecard(event)
        dimensions = scorecard["dimensions"]
        measure_lines = [
            f"- {row['dimension']}: measure {_fmt(row['measure'])}; z {_fmt(row['quant_z'])}"
            for row in dimensions
        ] or ["- No dimension-level measures were available."]
        dashboard = self._dashboard_link(event)
        as_of = scorecard.get("as_of") or "not available"
        text = (
            "Release-to-call quantitative processing is ready.\n\n"
            f"Ticker: {event.ticker}\nFiscal period: {event.fiscal_period}\n"
            f"Data as of: {as_of}\nCall time: {event.call_at.isoformat()}\n\n"
            "Measures and z-scores:\n"
            + "\n".join(measure_lines)
            + f"\n\nFreshness/workflow detail: {detail or 'none'}\nDashboard: {dashboard}\n"
        )
        rows = "".join(
            "<tr>"
            f"<td>{escape(str(row['dimension']))}</td>"
            f"<td>{escape(_fmt(row['measure']))}</td>"
            f"<td>{escape(_fmt(row['quant_z']))}</td>"
            "</tr>"
            for row in dimensions
        )
        table = (
            "<table cellpadding=\"6\" cellspacing=\"0\" border=\"1\">"
            "<tr><th>Dimension</th><th>Measure</th><th>Z-score</th></tr>"
            f"{rows or '<tr><td colspan=\"3\">No measures available</td></tr>'}</table>"
        )
        content = NotificationContent(
            subject=f"[Roz] {event.ticker} {event.fiscal_period} quant ready",
            text=text,
            html=_html_page(
                f"{event.ticker} {event.fiscal_period} quant ready",
                [
                    ("Freshness", f"As of {escape(str(as_of))}"),
                    ("Measures and z-scores", table),
                    (
                        "Links",
                        f'<a href="{escape(dashboard)}">Open dashboard</a>',
                    ),
                ],
            ),
        )
        return self._send_once(
            f"{event.provider_event_id}:pre-call-quant",
            content,
        )

    def final_combined(self, event: EarningsEvent, *, success: bool, detail: str = "") -> bool:
        if not success:
            return self.stall_failure(
                event,
                stage="post_call",
                attempts=None,
                detail=detail,
            )
        if self.state.notification_sent(f"{event.provider_event_id}:final:success") or (
            self.state.notification_sent(
                f"{event.provider_event_id}:final:recovery-success"
            )
        ):
            return False
        prior_failure = self.state.notification_key_exists(
            f"{event.provider_event_id}:failure"
        ) or self.state.notification_key_exists(
            f"operational:repeated_failure:{event.provider_event_id}"
        )
        scorecard = self._scorecard(event)
        dimensions = scorecard["dimensions"]
        dimension_lines = [
            (
                f"- {row['dimension']}: narrative {_fmt(row['narrative_level'])}; "
                f"change {_fmt(row['narrative_change'])}; quant z {_fmt(row['quant_z'])}; "
                f"gap {_fmt(row['narrative_quant_gap'])}"
                + ("; DIVERGENCE" if row["divergence"] else "")
                + (f"; evidence: {row['evidence']}" if row.get("evidence") else "")
            )
            for row in dimensions
        ] or ["- No dimension scorecard rows were available."]
        completion = scorecard["completion"]
        links = [self._dashboard_link(event), *scorecard.get("artifact_links", [])]
        if self.config and self.config.artifact_public_base_url:
            links.append(
                f"{self.config.artifact_public_base_url.rstrip('/')}/events/"
                f"{event.ticker}/{event.fiscal_period}"
            )
        outcome = "recovered and completed" if prior_failure else "completed"
        text = (
            f"Combined quant and post-call narrative processing {outcome}.\n\n"
            f"Ticker: {event.ticker}\nFiscal period: {event.fiscal_period}\n"
            f"Completion: {'complete' if completion['complete'] else 'incomplete'}\n"
            f"Issues: {', '.join(completion['issues']) or 'none'}\n\n"
            "Dimension scorecard:\n"
            + "\n".join(dimension_lines)
            + "\n\nDivergences: "
            + (
                ", ".join(row["dimension"] for row in scorecard["divergences"])
                or "none"
            )
            + f"\nWorkflow detail: {detail or 'none'}\nLinks:\n- "
            + "\n- ".join(links)
            + "\n"
        )
        rows = "".join(
            "<tr>"
            f"<td>{escape(str(row['dimension']))}</td>"
            f"<td>{escape(_fmt(row['narrative_level']))}</td>"
            f"<td>{escape(_fmt(row['narrative_change']))}</td>"
            f"<td>{escape(_fmt(row['quant_z']))}</td>"
            f"<td>{escape(_fmt(row['narrative_quant_gap']))}</td>"
            f"<td>{'Yes' if row['divergence'] else 'No'}</td>"
            "</tr>"
            for row in dimensions
        )
        table = (
            "<table cellpadding=\"6\" cellspacing=\"0\" border=\"1\"><tr>"
            "<th>Dimension</th><th>Narrative</th><th>Change</th><th>Quant z</th>"
            f"<th>Gap</th><th>Divergence</th></tr>{rows}</table>"
        )
        link_html = "<br>".join(
            f'<a href="{escape(link)}">{escape(link)}</a>' for link in links
        )
        content = NotificationContent(
            subject=(
                f"[Roz] {event.ticker} {event.fiscal_period} "
                f"{'recovery successful' if prior_failure else 'final completed'}"
            ),
            text=text,
            html=_html_page(
                f"{event.ticker} {event.fiscal_period} {outcome}",
                [
                    (
                        "Completion",
                        escape(
                            f"{'complete' if completion['complete'] else 'incomplete'}; "
                            f"issues: {', '.join(completion['issues']) or 'none'}"
                        ),
                    ),
                    ("Dimension scorecard", table),
                    ("Dashboard and artifacts", link_html),
                ],
            ),
        )
        return self._send_once(
            (
                f"{event.provider_event_id}:final:"
                f"{'recovery-success' if prior_failure else 'success'}"
            ),
            content,
        )

    def stall_failure(
        self,
        event: EarningsEvent,
        *,
        stage: str,
        attempts: int | None,
        detail: str,
        recovery: str | None = None,
    ) -> bool:
        action = recovery or (
            "Inspect the Operations timeline and worker logs, correct the source "
            "or credential issue, then allow the persisted bounded retry to resume."
        )
        attempts_text = str(attempts) if attempts is not None else "not available"
        dashboard = self._dashboard_link(event)
        content = NotificationContent(
            subject=f"[Roz] {event.ticker} {event.fiscal_period} stalled/failed",
            text=(
                f"Stage: {stage}\nAttempts: {attempts_text}\n"
                f"Ticker: {event.ticker}\nFiscal period: {event.fiscal_period}\n"
                f"Failure detail: {detail or 'not available'}\n"
                f"Recovery: {action}\nDashboard: {dashboard}\n"
            ),
            html=_html_page(
                f"{event.ticker} {event.fiscal_period} stalled/failed",
                [
                    (
                        "Failure",
                        escape(
                            f"Stage: {stage}; attempts: {attempts_text}; "
                            f"detail: {detail or 'not available'}"
                        ),
                    ),
                    ("Recovery", escape(action)),
                    ("Operations", f'<a href="{escape(dashboard)}">Open dashboard</a>'),
                ],
            ),
        )
        return self._send_once(f"{event.provider_event_id}:failure", content)

    def operational_alert(self, alert: Mapping[str, Any]) -> bool:
        kind = str(alert.get("kind") or "operational")
        event_id = str(alert.get("provider_event_id") or "monitor")
        stage = str(alert.get("state") or kind)
        attempts = alert.get("failures")
        detail = str(alert.get("detail") or "No detail available")
        recovery = {
            "stuck_event": "Inspect the event timeline, active job, and worker health.",
            "repeated_failure": "Correct the recurring workflow error; retain the existing retry history.",
            "stale_poller": "Check monitor process health and the latest poll-cycle error before restarting.",
            "artifact_publish_failed": "Correct R2 endpoint/credentials and restart the worker to resume persisted publication.",
        }.get(kind, "Inspect the Operations dashboard and service logs.")
        content = NotificationContent(
            subject=f"[Roz] operational alert: {kind}",
            text=(
                f"Signal: {kind}\nEvent: {event_id}\nStage: {stage}\n"
                f"Attempts: {_fmt(attempts)}\nDetail: {detail}\nRecovery: {recovery}\n"
            ),
            html=_html_page(
                f"Operational alert: {kind}",
                [
                    ("Signal", escape(f"Event: {event_id}; stage: {stage}")),
                    ("Detail", escape(detail)),
                    ("Recovery", escape(recovery)),
                ],
            ),
        )
        occurrence_fields = {
            key: alert.get(key)
            for key in (
                "occurrence",
                "failure_fingerprint",
                "updated_at",
                "started_at",
                "publication_key",
                "cycle_id",
            )
            if alert.get(key) not in (None, "")
        }
        # Producers attach a lifecycle anchor that remains stable while an
        # incident persists and changes after recovery. The fallback preserves
        # dedupe behavior for older/custom alert producers.
        occurrence = occurrence_fields or {
            "kind": kind,
            "event": event_id,
            "stage": stage,
        }
        fingerprint = hashlib.sha256(
            json.dumps(occurrence, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:20]
        return self._send_once(
            f"operational:{kind}:{event_id}:{fingerprint}",
            content,
        )

    def _scorecard(self, event: EarningsEvent) -> dict[str, Any]:
        if self.assembler:
            return self.assembler.assemble(event)
        return {
            "as_of": None,
            "dimensions": [],
            "divergences": [],
            "completion": {
                "complete": False,
                "dimension_count": 0,
                "dimensions_with_missing_values": 0,
                "issues": ["scorecard_not_configured"],
            },
            "artifact_links": [],
        }

    def _dashboard_link(self, event: EarningsEvent) -> str:
        base = self.config.dashboard_url if self.config else "http://localhost:8501"
        return (
            f"{base}?ticker={event.ticker}&fiscal_period={event.fiscal_period}"
            f"&event_id={event.provider_event_id}"
        )

    # Compatibility aliases for callers migrating from the original two-email names.
    def queued(self, event: EarningsEvent) -> bool:
        return self.pre_call_quant(event)

    def completed(self, event: EarningsEvent, *, success: bool, detail: str = "") -> bool:
        return self.final_combined(event, success=success, detail=detail)
