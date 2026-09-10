"""Write one Quartr MCP transcript payload into earnings or conference layout."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._write_quartr_mcp_transcript import paragraphs_to_text  # noqa: E402
from services.earnings_monitor.onboard_pull import write_conference_transcript  # noqa: E402

INV = ROOT / "data" / "case_study_pull" / "inventory.json"
RAW = ROOT / "Structured Narrative" / "transcripts_raw"
PULL = ROOT / "data" / "case_study_pull"


def _load_inv() -> dict[str, Any]:
    return json.loads(INV.read_text(encoding="utf-8"))


def _event_row(inv: dict[str, Any], ticker: str, event_id: int) -> dict[str, Any]:
    book = inv[ticker.strip().upper()]
    for row in book.get("events") or []:
        if int(row.get("event_id") or 0) == int(event_id):
            return row
    raise SystemExit(f"event {event_id} not in inventory for {ticker}")


def _merge_paragraphs(*payloads: dict[str, Any]) -> list[dict]:
    seen: set[object] = set()
    out: list[dict] = []
    for payload in payloads:
        for item in payload.get("paragraphs") or []:
            if not isinstance(item, dict):
                continue
            pid = item.get("paragraphId")
            key = pid if pid is not None else (item.get("start"), item.get("text"))
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    out.sort(key=lambda p: (float(p.get("start") or 0), str(p.get("paragraphId") or "")))
    return out


def write_event(
    *,
    ticker: str,
    event_id: int,
    payload: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ticker = ticker.strip().upper()
    inv = _load_inv()
    row = _event_row(inv, ticker, event_id)
    payloads = [payload]
    if extra:
        payloads.append(extra)
    paras = _merge_paragraphs(*payloads)
    text = paragraphs_to_text(paras)
    nxt = payload.get("nextFromTimestamp")
    if extra:
        nxt = extra.get("nextFromTimestamp") or nxt

    dest_dir = PULL / ticker
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / f"{event_id}_full.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    if extra:
        (dest_dir / f"{event_id}_qna.json").write_text(
            json.dumps(extra, indent=2) + "\n", encoding="utf-8"
        )

    kind = row.get("kind")
    if kind == "earnings":
        period = str(row.get("period") or "").strip()
        if not period:
            raise SystemExit(f"earnings event {event_id} missing period")
        RAW.mkdir(parents=True, exist_ok=True)
        dest = RAW / f"{ticker}_{period}.txt"
        dest.write_text((text + "\n") if text else "", encoding="utf-8")
        return {
            "ticker": ticker,
            "event_id": event_id,
            "kind": kind,
            "period": period,
            "path": str(dest),
            "n_paragraphs": len(paras),
            "bytes": dest.stat().st_size if dest.is_file() else 0,
            "nextFromTimestamp": nxt,
        }

    dest = write_conference_transcript(
        ROOT,
        ticker=ticker,
        event_id=event_id,
        event_date=str(row.get("date") or "")[:10],
        event_name=str(row.get("title") or f"event {event_id}"),
        payload={
            "eventId": event_id,
            "ticker": ticker,
            "title": row.get("title"),
            "date": row.get("date"),
            "paragraphs": paras,
            "text": text,
        },
    )
    return {
        "ticker": ticker,
        "event_id": event_id,
        "kind": kind,
        "period": None,
        "path": str(dest),
        "n_paragraphs": len(paras),
        "bytes": dest.stat().st_size if dest.is_file() else 0,
        "nextFromTimestamp": nxt,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--event-id", type=int, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--qna", type=Path, default=None)
    args = parser.parse_args()
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    extra = json.loads(args.qna.read_text(encoding="utf-8")) if args.qna else None
    result = write_event(
        ticker=args.ticker, event_id=args.event_id, payload=payload, extra=extra
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
