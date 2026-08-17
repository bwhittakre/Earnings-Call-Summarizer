"""Poll-cycle scaffold.

Replace ``discover_jobs`` with the grounded earnings-calendar integration. The
default intentionally emits no jobs, making an initial deployment shadow-safe.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import boto3

sqs = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")


def discover_jobs() -> list[dict]:
    return []


def handler(event, _context):
    queue_url = os.environ["QUEUE_URL"]
    table = dynamodb.Table(os.environ["STATE_TABLE_NAME"])
    shadow = os.getenv("SHADOW_MODE", "true").lower() == "true"
    jobs = discover_jobs()

    if not shadow:
        for job in jobs:
            sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(job))

    now = datetime.now(UTC).isoformat()
    table.put_item(
        Item={
            "pk": "poller",
            "sk": now,
            "discovered": len(jobs),
            "shadow": shadow,
            "event_source": event.get("source", "unknown"),
        }
    )
    return {"discovered": len(jobs), "enqueued": 0 if shadow else len(jobs), "shadow": shadow}
