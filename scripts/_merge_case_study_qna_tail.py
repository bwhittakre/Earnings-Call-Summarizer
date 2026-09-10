"""Merge an extra Q&A tail window into an existing case-study earnings pull."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._case_study_write_payload import write_event, _merge_paragraphs  # noqa: E402

PULL = ROOT / "data" / "case_study_pull"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--event-id", type=int, required=True)
    parser.add_argument("--tail", type=Path, required=True)
    args = parser.parse_args()
    ticker = args.ticker.strip().upper()
    dest = PULL / ticker
    payload = json.loads((dest / f"{args.event_id}_full.json").read_text(encoding="utf-8"))
    existing = dest / f"{args.event_id}_qna.json"
    extra_parts = []
    if existing.is_file():
        extra_parts.append(json.loads(existing.read_text(encoding="utf-8")))
    extra_parts.append(json.loads(args.tail.read_text(encoding="utf-8")))
    extra = {
        "eventId": args.event_id,
        "isLive": False,
        "paragraphs": _merge_paragraphs(*extra_parts),
        "nextFromTimestamp": extra_parts[-1].get("nextFromTimestamp"),
    }
    payload.pop("nextFromTimestamp", None)
    result = write_event(
        ticker=ticker, event_id=args.event_id, payload=payload, extra=extra
    )
    print(json.dumps({k: result[k] for k in ("event_id", "period", "bytes", "n_paragraphs", "nextFromTimestamp")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
