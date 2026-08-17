"""Portable role scaffolds used until application entry points are wired in."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
HEALTH_DIR = DATA_DIR / "health"
LOG = logging.getLogger("earnings-monitor")


def _write_health(role: str, **details: object) -> None:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"role": role, "updated_at": datetime.now(UTC).isoformat(), **details}
    (HEALTH_DIR / f"{role}.json").write_text(json.dumps(payload), encoding="utf-8")


def healthcheck() -> int:
    if not HEALTH_DIR.exists():
        return 1
    freshness = int(os.getenv("HEALTH_MAX_AGE_SECONDS", "900"))
    files = list(HEALTH_DIR.glob("*.json"))
    return 0 if files and any(time.time() - item.stat().st_mtime < freshness for item in files) else 1


def monitor() -> None:
    interval = int(os.getenv("MONITOR_INTERVAL_SECONDS", "300"))
    LOG.info("monitor scaffold started; shadow_mode=%s", os.getenv("SHADOW_MODE", "true"))
    while True:
        _write_health("monitor", shadow_mode=os.getenv("SHADOW_MODE", "true"))
        time.sleep(interval)


def worker() -> None:
    queue_url = os.getenv("QUEUE_URL", "")
    idle = int(os.getenv("WORKER_IDLE_SECONDS", "10"))
    LOG.info("worker scaffold started; queue=%s", queue_url or "local-idle")
    sqs = boto3.client("sqs") if queue_url else None
    while True:
        processed = 0
        if sqs:
            response = sqs.receive_message(
                QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=min(idle, 20)
            )
            for message in response.get("Messages", []):
                LOG.info("received scaffold job %s", message.get("MessageId"))
                # Wire the application processor here; do not acknowledge unprocessed jobs.
                processed += 1
        _write_health("worker", received=processed, queue_configured=bool(queue_url))
        if not sqs:
            time.sleep(idle)


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    role = sys.argv[1] if len(sys.argv) > 1 else "monitor"
    if role == "healthcheck":
        return healthcheck()
    if role == "monitor":
        monitor()
    elif role == "worker":
        worker()
    else:
        raise SystemExit(f"unsupported role: {role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
