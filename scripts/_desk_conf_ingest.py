"""Conference / supplemental event ingest → claims desk seeds.

Fetches a Quartr transcript for a non-earnings event (conference, AGM,
investor day), extracts promise/goal excerpts via Haiku, writes a
supplemental cue queue file, and optionally feeds it into the autopilot.

Architecture
------------
  1. Fetch transcript via Quartr REST API (same key as quartr_history_import)
  2. Flatten to speaker-labelled plain text
  3. LLM extraction (Haiku) — single-pass promise/goal classifier
  4. Write data/desk_conf_cue_{TICKER}.json (supplemental cue queue)
  5. (Optional) call autopilot.run_for_ticker with the supplemental rows merged

Usage
-----
    # Ingest a single conference and feed autopilot:
    python scripts/_desk_conf_ingest.py \\
        --ticker CRWV \\
        --event-id 746055 \\
        --event-date 2026-09-08 \\
        --event-name "Goldman Sachs 2026"

    # Dry-run (no LLM calls, no overlay writes):
    python scripts/_desk_conf_ingest.py --ticker CRWV --event-id 746055 \\
        --event-date 2026-09-08 --event-name "Goldman Sachs 2026" --dry-run

    # Extract only — write cue file but skip autopilot:
    python scripts/_desk_conf_ingest.py --ticker CRWV --event-id 746055 \\
        --event-date 2026-09-08 --event-name "Goldman Sachs 2026" --extract-only

Environment variables (same as quartr_history_import):
    QUARTR_API_KEY   — required
    QUARTR_API_BASE  — optional (default https://api.quartr.com)
    ANTHROPIC_API_KEY — required for extraction
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# ── paths ─────────────────────────────────────────────────────────────────────

DATA_DIR = ROOT / "data"
SN_DIR = ROOT / "Structured Narrative"


def _conf_cue_path(ticker: str) -> Path:
    return DATA_DIR / f"desk_conf_cue_{ticker.upper()}.json"


# ── Quartr transcript fetch ───────────────────────────────────────────────────

def _fetch_transcript_text(event_id: int | str) -> str:
    """Fetch transcript text for a Quartr event ID using the REST API."""
    # Reuse QuartrApiClient from the history importer
    sys.path.insert(0, str(SN_DIR))
    from quartr_history_import import QuartrApiClient, extract_transcript_text  # type: ignore

    client = QuartrApiClient()

    # Get transcript document(s) for this event
    transcripts = client.list_transcripts_for_event(event_id)
    if not transcripts:
        raise RuntimeError(
            f"No transcript documents found for event_id={event_id}. "
            "The event may not have a transcript yet."
        )

    # Prefer the longest / most complete document
    doc = max(transcripts, key=lambda d: int(d.get("characterCount") or d.get("wordCount") or 0))
    doc_id = doc.get("id")
    if not doc_id:
        raise RuntimeError(f"Transcript document has no id: {doc}")

    print(f"  [quartr] event {event_id} → document {doc_id} "
          f"({doc.get('characterCount', '?')} chars)")
    text = client.fetch_transcript_text(doc_id)
    if not text:
        raise RuntimeError(f"Transcript document {doc_id} returned empty text")
    return text


def _load_transcript_from_file(path: str | Path) -> str:
    """Load transcript text from a local file.

    Accepts:
    - Plain text (.txt) — returned as-is.
    - JSON payloads from Quartr MCP read_transcript (.json) — flattened to
      speaker-labelled text using the same logic as _write_quartr_mcp_transcript.py.
    """
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"Transcript file not found: {p}")

    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        # Quartr MCP payload format
        sys.path.insert(0, str(SN_DIR))
        from quartr_history_import import extract_transcript_text  # type: ignore
        data = json.loads(raw)
        # Try the standard extraction first
        text = extract_transcript_text(data)
        if not text:
            # Try paragraphs-to-text (MCP format may have speakerName)
            paragraphs = data.get("paragraphs") or []
            chunks: list[str] = []
            last_speaker = ""
            for item in (paragraphs if isinstance(paragraphs, list) else []):
                if not isinstance(item, dict):
                    continue
                t = str(item.get("text") or "").strip()
                if not t:
                    continue
                speaker = str(item.get("speakerName") or item.get("speaker") or "").strip()
                if speaker and speaker != last_speaker:
                    chunks.append(f"{speaker}:")
                    last_speaker = speaker
                chunks.append(t)
            text = "\n".join(chunks).strip()
        if not text:
            raise RuntimeError(f"Could not extract text from JSON payload: {p}")
        return text
    else:
        return raw.strip()


# ── LLM extraction ────────────────────────────────────────────────────────────

EXTRACT_SYSTEM = textwrap.dedent("""
    You are an experienced equity analyst reviewing a transcript from a company
    presentation at an investor conference or AGM. Your task: extract every
    forward-looking statement where management makes a SPECIFIC, TRACKABLE
    promise, goal, or commitment.

    A strong candidate:
    - Is a SPECIFIC, TRACKABLE commitment or goal — management said they WILL do
      something concrete, or WANT to achieve something measurable.
    - Has at least one clear object (a product, metric, initiative, or entity)
      that could be looked up in future earnings call transcripts.
    - Is NOT routine guidance ranges, vague aspirational language, or IR boilerplate.
    - Has a realistic resolution window: 1–12 quarters.

    Classify each candidate:
      class: "promise"  — management commits to a future action (will, plan to, expect to)
      class: "goal"     — management states a desire/ambition (want, aim, targeting)

    Assign a dimension from this list (pick the best match):
      revenue_growth, margin_expansion, product_roadmap, market_share, cost_reduction,
      capex_investment, geographic_expansion, r_and_d, talent_hiring, regulatory,
      partnerships, customer_retention, technology_platform, capital_return, other

    For each candidate extract the VERBATIM excerpt from the transcript (1–3 sentences).

    Return valid JSON only — no prose, no markdown fences — in this exact schema:
    {
      "excerpts": [
        {
          "class": "promise" | "goal",
          "dimension": "<one of the listed dimensions>",
          "excerpt": "<verbatim quote from transcript>"
        }
      ]
    }

    Return an empty array if there are no strong candidates. Quality over quantity.
""").strip()


def _extract_excerpts(
    text: str,
    ticker: str,
    event_name: str,
    *,
    client: Any,
    max_chars: int = 80_000,
) -> list[dict]:
    """Call Haiku to extract promise/goal excerpts from transcript text."""
    from src.llm.anthropic_client import extract_json  # noqa: E402

    truncated = text[:max_chars]
    if len(text) > max_chars:
        print(f"  [extract] truncating transcript to {max_chars:,} chars "
              f"(full: {len(text):,})")

    user_msg = (
        f"Company: {ticker.upper()}\n"
        f"Event: {event_name}\n\n"
        f"--- TRANSCRIPT ---\n{truncated}\n--- END ---\n\n"
        "Extract all forward-looking promises and goals. Return JSON only."
    )

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text if response.content else ""
    try:
        data = extract_json(raw)
        return data.get("excerpts") or []
    except Exception as exc:
        print(f"  [extract] JSON parse error: {exc}. Raw snippet: {raw[:200]}",
              file=sys.stderr)
        return []


# ── Supplemental cue file I/O ─────────────────────────────────────────────────

def _load_conf_cue(ticker: str) -> dict:
    path = _conf_cue_path(ticker)
    if not path.is_file():
        return {"ticker": ticker.upper(), "source": "conference", "events": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_conf_cue(ticker: str, payload: dict) -> Path:
    path = _conf_cue_path(ticker)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _event_to_cue_rows(event: dict) -> list[dict]:
    """Convert a stored conference event to autopilot cue rows.

    Each row matches the shape of a `missed` entry:
      {ticker, fiscal_period, class, dimension, excerpt}
    """
    ticker = event.get("ticker", "")
    date = event.get("date", "")
    fp = f"CONF-{date}" if date else "CONF-unknown"
    rows = []
    for ex in event.get("excerpts") or []:
        rows.append({
            "ticker": ticker,
            "fiscal_period": fp,
            "class": ex.get("class", "goal"),
            "dimension": ex.get("dimension", "other"),
            "excerpt": ex.get("excerpt", ""),
        })
    return rows


# ── Main pipeline ─────────────────────────────────────────────────────────────

def ingest_conference(
    ticker: str,
    event_id: int | str,
    event_date: str,
    event_name: str,
    *,
    dry_run: bool = False,
    extract_only: bool = False,
    budget_usd: float = 0.25,
    transcript_file: str | Path | None = None,
) -> list[dict]:
    """Full pipeline: fetch → extract → write cue file → (autopilot).

    Args:
        transcript_file: optional path to a pre-downloaded transcript file
                         (.txt plain text or .json Quartr MCP payload).
                         When provided, skips the REST API fetch.

    Returns the list of extracted cue rows.
    """
    import anthropic  # noqa: E402

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    client = anthropic.Anthropic(api_key=api_key)

    ticker_up = ticker.upper()
    fp_label = f"CONF-{event_date}"
    print(f"\n{'='*60}")
    print(f"  Conference ingest: {ticker_up} | {event_name} | {fp_label}")
    if dry_run:
        print("  [DRY RUN]")
    print(f"{'='*60}")

    # 1. Fetch transcript (from file or REST API)
    if transcript_file:
        print(f"  [1/4] Loading transcript from file: {transcript_file} …")
        text = _load_transcript_from_file(transcript_file)
    else:
        print(f"  [1/4] Fetching transcript for event {event_id} via REST …")
        text = _fetch_transcript_text(event_id)
    print(f"  [1/4] Got {len(text):,} chars")

    # 2. Extract excerpts via Haiku
    print("  [2/4] Extracting promises/goals via Haiku …")
    excerpts: list[dict] = []
    if not dry_run:
        excerpts = _extract_excerpts(text, ticker_up, event_name, client=client)
    print(f"  [2/4] {len(excerpts)} excerpts extracted")

    # 3. Write supplemental cue file
    print("  [3/4] Updating supplemental cue file …")
    cue_payload = _load_conf_cue(ticker_up)
    cue_payload["ticker"] = ticker_up

    # Remove any pre-existing entry for the same event_id
    existing = cue_payload.get("events") or []
    existing = [e for e in existing if str(e.get("event_id")) != str(event_id)]

    new_event: dict = {
        "event_id": int(event_id),
        "date": event_date,
        "name": event_name,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker_up,
        "excerpts": excerpts,
    }
    existing.append(new_event)
    cue_payload["events"] = existing

    if not dry_run:
        out_path = _save_conf_cue(ticker_up, cue_payload)
        print(f"  [3/4] Wrote {out_path}")
    else:
        print(f"  [3/4] [dry-run] would write {_conf_cue_path(ticker_up)}")

    # 4. Build cue rows for autopilot
    cue_rows = _event_to_cue_rows(new_event)
    print(f"  [4/4] {len(cue_rows)} supplemental cue rows ready")

    if extract_only or dry_run:
        print("  [4/4] [skip] autopilot (--extract-only or --dry-run)")
        return cue_rows

    # 5. Feed into autopilot via supplemental path
    if cue_rows:
        print("  [4/4] Feeding supplemental rows into autopilot …")
        _run_autopilot_with_supplemental(ticker_up, cue_rows, budget_usd=budget_usd)
    else:
        print("  [4/4] No cue rows extracted — skipping autopilot")

    return cue_rows


def _run_autopilot_with_supplemental(
    ticker: str,
    supplemental_rows: list[dict],
    *,
    budget_usd: float = 0.25,
) -> None:
    """Write a temp supplemental cue file and call the autopilot."""
    # Write a temp file that the autopilot's --supplemental-cue-file flag reads
    import tempfile
    tmp = Path(tempfile.mktemp(suffix=".json", prefix=f"conf_supp_{ticker}_"))
    tmp.write_text(json.dumps(supplemental_rows), encoding="utf-8")
    try:
        import subprocess
        cmd = [
            sys.executable, "scripts/_desk_autopilot.py",
            "--ticker", ticker,
            "--supplemental-cue-file", str(tmp),
            "--budget-usd", str(budget_usd),
        ]
        print(f"  cmd: {' '.join(cmd)}")
        subprocess.run(cmd, cwd=str(ROOT), check=False)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ticker", required=True, metavar="TICKER",
                        help="Company ticker (e.g. CRWV)")
    parser.add_argument("--event-id", required=True, type=int, metavar="ID",
                        help="Quartr event ID")
    parser.add_argument("--event-date", required=True, metavar="YYYY-MM-DD",
                        help="Conference date (ISO format)")
    parser.add_argument("--event-name", required=True, metavar="NAME",
                        help="Human-readable event name")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and parse but do NOT write files or call LLM")
    parser.add_argument("--extract-only", action="store_true",
                        help="Extract and write cue file but do NOT run autopilot")
    parser.add_argument("--budget-usd", type=float, default=0.25,
                        help="Autopilot Sonnet budget cap for this run (default 0.25)")
    parser.add_argument("--transcript-file", metavar="PATH",
                        help="Path to pre-downloaded transcript (.txt or .json Quartr payload). "
                             "Skips REST API fetch when provided.")
    args = parser.parse_args()

    try:
        rows = ingest_conference(
            args.ticker,
            args.event_id,
            args.event_date,
            args.event_name,
            dry_run=args.dry_run,
            extract_only=args.extract_only,
            budget_usd=args.budget_usd,
            transcript_file=getattr(args, "transcript_file", None),
        )
        print(f"\n  Done — {len(rows)} cue rows for {args.ticker} {args.event_name}")
        return 0
    except Exception as exc:
        print(f"\n  [ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
