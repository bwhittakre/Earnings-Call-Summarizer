"""Quartr → inbox live transcript sweeper (MCP/automation first).

Drops atomic ``*.transcript.json`` bundles for ``LocalInboxProvider``.
Access is behind ``QuartrGateway`` so a REST client can plug in later without
rewriting the sweeper. Distinct from ``providers.QuartrGateway`` (event search
+ fetch used by discovery adapters).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .providers import write_transcript_bundle_atomic

LOG = logging.getLogger(__name__)


class QuartrGateway(Protocol):
    """Injectable transcript source for the live sweeper."""

    def fetch_transcript(self, event_id: str) -> Mapping[str, Any]:
        """Return a Quartr-shaped transcript payload.

        Expected keys (MCP ``read_transcript`` shape):
        ``isLive``, ``lastTimestamp``, ``paragraphs``, optional ``eventId``,
        optional document/source URL fields.
        """
        ...

    def get_event(self, event_id: str) -> Mapping[str, Any] | None:
        """Optional event metadata (ticker/period). Default: unavailable."""
        ...


class JsonDumpGateway:
    """Read a saved MCP ``read_transcript`` JSON dump from disk."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def fetch_transcript(self, event_id: str) -> Mapping[str, Any]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"dump must be a JSON object: {self.path}")
        dumped_id = payload.get("eventId")
        if dumped_id is not None and str(dumped_id) != str(event_id):
            LOG.warning(
                "dump eventId=%s differs from --event-id=%s; using CLI event id",
                dumped_id,
                event_id,
            )
        return payload

    def get_event(self, event_id: str) -> Mapping[str, Any] | None:
        return None


class CallableGateway:
    """Inject a Python callable (Cursor automation / tests)."""

    def __init__(
        self,
        fetch: Callable[[str], Mapping[str, Any]],
        *,
        get_event: Callable[[str], Mapping[str, Any] | None] | None = None,
    ):
        self._fetch = fetch
        self._get_event = get_event

    def fetch_transcript(self, event_id: str) -> Mapping[str, Any]:
        payload = self._fetch(event_id)
        if not isinstance(payload, Mapping):
            raise ValueError("callable must return a mapping")
        return payload

    def get_event(self, event_id: str) -> Mapping[str, Any] | None:
        if self._get_event is None:
            return None
        return self._get_event(event_id)


class RestQuartrGateway:
    """Stub for a future live REST client — not implemented in v1."""

    def __init__(self, *args: Any, **kwargs: Any):
        raise NotImplementedError(
            "RestQuartrGateway is not implemented in v1; use JsonDumpGateway "
            "or CallableGateway (MCP/automation). See docs/earnings-monitor-setup.md."
        )

    def fetch_transcript(self, event_id: str) -> Mapping[str, Any]:
        raise NotImplementedError

    def get_event(self, event_id: str) -> Mapping[str, Any] | None:
        raise NotImplementedError


@dataclass(frozen=True)
class SweepTarget:
    event_id: str
    ticker: str
    fiscal_period: str
    inbox: Path
    source_url: str | None = None
    speaker_map: Mapping[str, str] | None = None


def _speaker_label(name: Any, speaker_map: Mapping[str, str] | None) -> str:
    key = str(name or "").strip()
    if speaker_map and key in speaker_map:
        return speaker_map[key]
    return f"Speaker {key}" if key else "Speaker"


def _paragraphs_to_speaker_text(
    paragraphs: list[Any], *, speaker_map: Mapping[str, str] | None
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in paragraphs:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        speaker = item.get("speakerName")
        if speaker is None:
            speaker = item.get("speaker")
        out.append({"speaker": _speaker_label(speaker, speaker_map), "text": text})
    return out


def _source_url_from_payload(
    payload: Mapping[str, Any], paragraphs: list[Any], event_id: str
) -> str | None:
    for key in ("sourceUrl", "source_url", "url"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for item in paragraphs:
        if isinstance(item, Mapping) and item.get("url"):
            return str(item["url"])
    company_id = payload.get("companyId") or payload.get("company_id")
    if company_id is not None:
        return (
            f"https://web.quartr.com/companies/{company_id}/events/{event_id}/overview"
        )
    return None


def mcp_payload_to_bundle(
    payload: Mapping[str, Any],
    *,
    event_id: str,
    ticker: str,
    fiscal_period: str,
    force_final: bool = False,
    source_url: str | None = None,
    speaker_map: Mapping[str, str] | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Map a Quartr MCP ``read_transcript`` payload to a v1 inbox bundle."""
    paragraphs = list(payload.get("paragraphs") or [])
    speaker_text = _paragraphs_to_speaker_text(paragraphs, speaker_map=speaker_map)
    if not speaker_text:
        raise ValueError("no usable speaker_text paragraphs in Quartr payload")

    is_live = bool(payload.get("isLive")) and not force_final
    status = "live" if is_live else "final"
    last_ts = payload.get("lastTimestamp")
    doc_id = (
        f"quartr-live-{event_id}-{last_ts}"
        if is_live
        else f"quartr-final-{event_id}"
    )
    resolved_url = source_url or _source_url_from_payload(payload, paragraphs, event_id)
    stamp = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    observed = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle: dict[str, Any] = {
        "schema_version": 1,
        "provider_event_id": str(event_id),
        "provider_document_id": doc_id,
        "ticker": ticker.strip().upper(),
        "fiscal_period": fiscal_period.strip().upper(),
        "status": status,
        "observed_at": observed,
        "speaker_text": speaker_text,
    }
    if resolved_url:
        bundle["source_url"] = resolved_url
    return bundle


def inbox_bundle_path(inbox: Path, ticker: str, fiscal_period: str) -> Path:
    return inbox / f"{ticker.strip().upper()}-{fiscal_period.strip().upper()}.transcript.json"


def write_sweep_bundle(
    gateway: QuartrGateway,
    target: SweepTarget,
    *,
    force_final: bool = False,
) -> dict[str, Any]:
    """Fetch once and atomically write the inbox transcript bundle."""
    payload = gateway.fetch_transcript(target.event_id)
    bundle = mcp_payload_to_bundle(
        payload,
        event_id=target.event_id,
        ticker=target.ticker,
        fiscal_period=target.fiscal_period,
        force_final=force_final,
        source_url=target.source_url,
        speaker_map=target.speaker_map,
    )
    target.inbox.mkdir(parents=True, exist_ok=True)
    path = write_transcript_bundle_atomic(
        inbox_bundle_path(target.inbox, target.ticker, target.fiscal_period),
        bundle,
    )
    chars = sum(len(row["text"]) for row in bundle["speaker_text"])
    return {
        "wrote": str(path),
        "status": bundle["status"],
        "chars": chars,
        "paragraphs": len(bundle["speaker_text"]),
        "provider_event_id": bundle["provider_event_id"],
        "provider_document_id": bundle["provider_document_id"],
        "is_live": bundle["status"] == "live",
    }


def run_sweep_loop(
    gateway: QuartrGateway,
    target: SweepTarget,
    *,
    interval_seconds: float = 30.0,
    max_minutes: float | None = None,
    force_final_on_exit: bool = True,
) -> dict[str, Any]:
    """Poll until ``isLive`` is false (or ``max_minutes``), then write final."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    started = time.monotonic()
    last: dict[str, Any] | None = None
    while True:
        last = write_sweep_bundle(gateway, target, force_final=False)
        LOG.info(
            "sweep event=%s status=%s chars=%s",
            target.event_id,
            last["status"],
            last["chars"],
        )
        if not last["is_live"]:
            return last
        if max_minutes is not None:
            elapsed_min = (time.monotonic() - started) / 60.0
            if elapsed_min >= max_minutes:
                if force_final_on_exit:
                    return write_sweep_bundle(gateway, target, force_final=True)
                return last
        time.sleep(interval_seconds)


def _load_speaker_map(path: Path | None) -> Mapping[str, str] | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise SystemExit("--speaker-map must be a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.earnings_monitor.quartr_sweep",
        description=(
            "Sweep a Quartr transcript into an atomic inbox *.transcript.json "
            "bundle (MCP JSON dump or injectable callable)."
        ),
    )
    parser.add_argument("--event-id", required=True, help="Quartr event id")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--period", required=True, help="Fiscal period, e.g. FY2026-Q2")
    parser.add_argument("--inbox", required=True, type=Path, help="Inbox directory")
    parser.add_argument(
        "--from-json",
        type=Path,
        help="Path to MCP read_transcript JSON dump (JsonDumpGateway)",
    )
    parser.add_argument(
        "--final",
        action="store_true",
        help="Force status=final on this write",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Poll until isLive is false (or --max-minutes), then finalize",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=30.0,
        help="Loop poll interval (default 30)",
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        help="Stop looping after N minutes and force final",
    )
    parser.add_argument(
        "--source-url",
        default=None,
        help="Override source_url on the written bundle",
    )
    parser.add_argument(
        "--speaker-map",
        type=Path,
        default=None,
        help="Optional JSON map of speakerName -> display label",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)
    if args.from_json is None:
        print(
            "error: --from-json is required in v1 (MCP dump). "
            "RestQuartrGateway is not implemented yet.",
            file=sys.stderr,
        )
        return 2
    gateway: QuartrGateway = JsonDumpGateway(args.from_json)
    target = SweepTarget(
        event_id=str(args.event_id),
        ticker=args.ticker,
        fiscal_period=args.period,
        inbox=Path(args.inbox),
        source_url=args.source_url,
        speaker_map=_load_speaker_map(args.speaker_map),
    )
    if args.loop:
        result = run_sweep_loop(
            gateway,
            target,
            interval_seconds=args.interval_seconds,
            max_minutes=args.max_minutes,
            force_final_on_exit=True,
        )
    else:
        result = write_sweep_bundle(gateway, target, force_final=args.final)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
