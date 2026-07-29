"""Idempotent SMTP notifications for queue and completion milestones."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from .config import MonitorConfig
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
                client.starttls()
            if self.config.smtp_username:
                client.login(self.config.smtp_username, self.config.smtp_password or "")
            client.send_message(message)


class TwoEmailNotifier:
    """Sends quant-ready before the call and one final combined outcome."""

    def __init__(
        self,
        *,
        state: OperationalState,
        sender: MailSender,
        sender_address: str,
        recipients: tuple[str, ...],
    ):
        self.state = state
        self.sender = sender
        self.sender_address = sender_address
        self.recipients = recipients

    def _send_once(self, key: str, subject: str, body: str) -> bool:
        if self.state.notification_sent(key):
            return False
        message = EmailMessage()
        message["From"] = self.sender_address
        message["To"] = ", ".join(self.recipients)
        message["Subject"] = subject
        message.set_content(body)
        self.sender.send(message)
        self.state.mark_notification_sent(key)
        return True

    def pre_call_quant(self, event: EarningsEvent, *, detail: str = "") -> bool:
        return self._send_once(
            f"{event.provider_event_id}:pre-call-quant",
            f"[Earnings Monitor] {event.ticker} {event.fiscal_period} pre-call quant ready",
            f"Release data is fresh and the quant workflow completed before the call.\n\n"
            f"Ticker: {event.ticker}\nFiscal period: {event.fiscal_period}\n"
            f"Call time: {event.call_at.isoformat()}\nDetail: {detail or 'none'}\n",
        )

    def final_combined(self, event: EarningsEvent, *, success: bool, detail: str = "") -> bool:
        outcome = "completed" if success else "failed"
        return self._send_once(
            f"{event.provider_event_id}:final",
            f"[Earnings Monitor] {event.ticker} {event.fiscal_period} final {outcome}",
            f"Combined quant and post-call narrative processing {outcome}.\n\nTicker: {event.ticker}\n"
            f"Fiscal period: {event.fiscal_period}\nDetail: {detail or 'none'}\n",
        )

    # Compatibility aliases for callers migrating from the original two-email names.
    def queued(self, event: EarningsEvent) -> bool:
        return self.pre_call_quant(event)

    def completed(self, event: EarningsEvent, *, success: bool, detail: str = "") -> bool:
        return self.final_combined(event, success=success, detail=detail)
