"""Derive a provisional CEO regime stub for tickers missing from the catalog.

Source: the transcript-index roster (Structured Narrative/transcripts_index/<TICKER>/
index files). If roster titles are missing, falls back to a Haiku call over the
first management turns.

Writes the entry to config/management_regimes_overlay.json (which
load_management_regimes will pick up automatically).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_regimes import load_management_regimes, regimes_for_ticker  # noqa: E402

_OVERLAY_PATH = ROOT / "config" / "management_regimes_overlay.json"
_INDEX_ROOT = ROOT / "Structured Narrative" / "transcripts_index"

# Roles we care about for the stub
_CEO_TITLES = frozenset({
    "chief executive officer", "ceo", "president and ceo", "president & ceo",
    "co-ceo", "executive chairman", "chairman and ceo",
})


def _load_overlay() -> list[dict]:
    if not _OVERLAY_PATH.exists():
        return []
    try:
        raw = json.loads(_OVERLAY_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _save_overlay(entries: list[dict]) -> None:
    _OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OVERLAY_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _index_files_for(ticker: str) -> list[Path]:
    """Return all index JSON files for a ticker, sorted by name."""
    base = _INDEX_ROOT / ticker.upper()
    if not base.is_dir():
        return []
    return sorted(base.glob("*.json"))


def _extract_roster_speakers(index_files: list[Path]) -> list[dict]:
    """Extract speaker entries with CEO-like titles from index files.

    Index paragraphs have: {speaker, role, title?, ...}
    We want management speakers with CEO-like titles.
    """
    speakers: dict[str, dict] = {}  # name → {title, first_fiscal, last_fiscal}
    for path in index_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        fiscal = data.get("fiscal_period") or (
            path.stem.split("_")[-1] if "_" in path.stem else path.stem
        )
        for para in data.get("paragraphs") or []:
            if not isinstance(para, dict):
                continue
            speaker = str(para.get("speaker") or "").strip()
            title = str(para.get("title") or "").strip()
            role = str(para.get("role") or "").strip()
            if not speaker or role not in ("management", "ir"):
                continue
            title_lower = title.lower()
            is_ceo = any(t in title_lower for t in _CEO_TITLES)
            if not is_ceo:
                continue
            if speaker not in speakers:
                speakers[speaker] = {
                    "title": title,
                    "first_fiscal": fiscal,
                    "last_fiscal": fiscal,
                }
            else:
                from scripts._desk_trees_v2 import fiscal_key
                existing = speakers[speaker]
                if fiscal_key(fiscal) < fiscal_key(existing["first_fiscal"]):
                    existing["first_fiscal"] = fiscal
                if fiscal_key(fiscal) > fiscal_key(existing["last_fiscal"]):
                    existing["last_fiscal"] = fiscal
                if not existing.get("title") and title:
                    existing["title"] = title
    return [{"name": n, **v} for n, v in speakers.items()]


def _haiku_stub(ticker: str, first_turns: str, api_key: str) -> dict | None:
    """Last resort: ask Haiku who the CEO is from the first management turns."""
    try:
        import anthropic
        import re as _re

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": (
                    f"From this earnings call excerpt for {ticker}, identify the CEO "
                    f"(Chief Executive Officer). "
                    f"Return ONLY a JSON object: "
                    f'{{\"name\": \"<full name>\", \"title\": \"<exact title>\", '
                    f'\"start_fiscal\": null, \"end_fiscal\": null}}. '
                    f"If you cannot identify the CEO, return null.\n\n{first_turns[:2000]}"
                ),
            }],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        m = _re.search(r"\{[^}]+\}", text)
        if m:
            data = json.loads(m.group())
            if data and data.get("name"):
                return data
    except Exception:
        pass
    return None


def derive_regime_stub(
    ticker: str,
    *,
    api_key: str | None = None,
    force: bool = False,
) -> dict | None:
    """Derive and save a provisional CEO regime stub for `ticker`.

    Returns the new regime entry, or None if already catalogued or can't derive.
    If `force` is True, re-derives even if an entry already exists.
    """
    all_regimes = load_management_regimes()
    existing = regimes_for_ticker(ticker, all_regimes)
    if existing and not force:
        return None  # already catalogued

    index_files = _index_files_for(ticker)
    roster = _extract_roster_speakers(index_files) if index_files else []

    entry: dict | None = None
    if roster:
        from scripts._desk_trees_v2 import fiscal_key
        roster.sort(key=lambda s: fiscal_key(s.get("first_fiscal") or ""))
        speaker = roster[0]
        entry = {
            "ticker": ticker.upper(),
            "role": "CEO",
            "named_person": speaker["name"],
            "start_fiscal": speaker["first_fiscal"],
            "end_fiscal": (
                None if speaker["last_fiscal"] == speaker["first_fiscal"]
                else speaker["last_fiscal"]
            ),
            "source": "transcript_roster",
            "provisional": True,
            "derived_at": datetime.now(timezone.utc).isoformat(),
        }
    elif api_key and index_files:
        # Haiku fallback: read first few management turns from the earliest index
        index_files_sorted = sorted(index_files)
        turns = ""
        fiscal = ""
        try:
            data = json.loads(index_files_sorted[0].read_text(encoding="utf-8"))
            fiscal = (data or {}).get("fiscal_period") or ""
            turns = "\n".join(
                str(p.get("text") or "")[:200]
                for p in (data.get("paragraphs") or [])
                if isinstance(p, dict) and str(p.get("role") or "") == "management"
            )[:2000]
        except Exception:
            pass
        stub = _haiku_stub(ticker, turns, api_key) if turns else None
        if stub:
            entry = {
                "ticker": ticker.upper(),
                "role": "CEO",
                "named_person": stub.get("name") or "Unknown",
                "start_fiscal": stub.get("start_fiscal") or fiscal or None,
                "end_fiscal": stub.get("end_fiscal") or None,
                "source": "haiku_triage",
                "provisional": True,
                "derived_at": datetime.now(timezone.utc).isoformat(),
            }

    if not entry:
        return None

    overlay = _load_overlay()
    # Remove any existing overlay entry for this ticker/role
    overlay = [
        e for e in overlay
        if not (
            str(e.get("ticker") or "").upper() == ticker.upper()
            and str(e.get("role") or "") == "CEO"
        )
    ]
    overlay.append(entry)
    _save_overlay(overlay)
    return entry


def ensure_regime_stubs(
    tickers: list[str],
    *,
    api_key: str | None = None,
) -> dict[str, dict | None]:
    """Derive stubs for any tickers not in the base catalog.

    Returns a ticker→entry map; None means already catalogued (no new stub needed).
    """
    all_regimes = load_management_regimes()
    results: dict[str, dict | None] = {}
    for ticker in tickers:
        existing = regimes_for_ticker(ticker, all_regimes)
        if existing:
            results[ticker] = None  # already catalogued
            continue
        stub = derive_regime_stub(ticker, api_key=api_key)
        results[ticker] = stub
        if stub:
            print(
                f"  [regimes] {ticker}: provisional stub from "
                f"{stub.get('source')} → {stub.get('named_person')}"
            )
        else:
            print(f"  [regimes] {ticker}: could not derive stub")
    return results
