#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bridge earnings-scraper inbox/ -> Structured Narrative transcripts_raw/.

Reads ROIC fetch output (``# company:`` / ``# period:`` header + transcript body)
and writes files in the format ``LocalFileProvider`` expects:
``transcripts_raw/{TICKER}_{FYyyyy-Qn}.txt``.

Default inbox (first match wins):
  1. ``EARNINGS_SCRAPER_INBOX`` env var
  2. ``../earnings-scraper-main/earnings-scraper-main/inbox`` (Desktop zip layout)
  3. ``../earnings-scraper-main/inbox``

Examples
--------
    python "Structured Narrative/export_inbox_to_transcripts_raw.py"
    python "Structured Narrative/export_inbox_to_transcripts_raw.py" --dry-run
    python "Structured Narrative/export_inbox_to_transcripts_raw.py" --ticker AMZN --force
    python "Structured Narrative/export_inbox_to_transcripts_raw.py" \\
        --inbox "C:/path/to/earnings-scraper-main/inbox"
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "transcripts_raw"

_HEADER_RE = re.compile(r"^#\s*([^:]+):\s*(.*)$")
_PERIOD_SPACED_RE = re.compile(r"^FY\s*(\d{4})\s*Q([1-4])\s*$", re.IGNORECASE)
_PERIOD_HYPHEN_RE = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)
_FILENAME_RE = re.compile(r"^([a-z0-9]+)-fy(\d{4})-q([1-4])", re.IGNORECASE)


@dataclass
class InboxTranscript:
    ticker: str
    fiscal_period: str
    body: str
    source: Path


@dataclass
class SkipResult:
    source: Path
    reason: str


def default_inbox() -> Path | None:
    env = os.environ.get("EARNINGS_SCRAPER_INBOX", "").strip()
    if env:
        return Path(env).expanduser()

    desktop = HERE.parent.parent
    candidates = [
        desktop / "earnings-scraper-main" / "earnings-scraper-main" / "inbox",
        desktop / "earnings-scraper-main" / "inbox",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def normalize_fiscal_period(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    m = _PERIOD_HYPHEN_RE.match(text)
    if m:
        return f"FY{m.group(1)}-Q{m.group(2)}"
    spaced = text.replace("-", " ")
    m = _PERIOD_SPACED_RE.match(spaced)
    if m:
        return f"FY{m.group(1)}-Q{m.group(2)}"
    return None


def fiscal_period_from_filename(path: Path) -> tuple[str, str] | None:
    m = _FILENAME_RE.match(path.stem)
    if not m:
        return None
    ticker = m.group(1).upper()
    fiscal_period = f"FY{m.group(2)}-Q{m.group(3)}"
    return ticker, fiscal_period


def parse_inbox_file(path: Path) -> InboxTranscript | SkipResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    headers: dict[str, str] = {}
    body_lines: list[str] = []
    in_header = True

    for line in text.splitlines():
        if in_header:
            m = _HEADER_RE.match(line)
            if m:
                headers[m.group(1).strip().lower()] = m.group(2).strip()
                continue
            if not line.strip():
                continue
            in_header = False
        body_lines.append(line)

    body = "\n".join(body_lines).strip()
    if not body:
        return SkipResult(path, "empty transcript body")

    ticker = headers.get("company", "").upper()
    event = headers.get("event", "earnings-call").lower()
    fiscal_period = normalize_fiscal_period(headers.get("period", ""))

    fallback = fiscal_period_from_filename(path)
    if fallback:
        file_ticker, file_period = fallback
        ticker = ticker or file_ticker
        fiscal_period = fiscal_period or file_period

    if event != "earnings-call":
        return SkipResult(path, f"event={event!r} (not an earnings-call transcript)")
    if not ticker:
        return SkipResult(path, "could not resolve ticker")
    if not fiscal_period:
        return SkipResult(path, f"could not parse fiscal period from {headers.get('period', path.name)!r}")

    return InboxTranscript(ticker=ticker, fiscal_period=fiscal_period, body=body, source=path)


def export_transcript(
    item: InboxTranscript,
    out_dir: Path,
    *,
    force: bool,
    dry_run: bool,
) -> str:
    dest = out_dir / f"{item.ticker}_{item.fiscal_period}.txt"
    if dest.exists() and not force:
        return f"= skip (exists): {dest.name}"
    if dry_run:
        return f"~ would write: {dest.name}  <- {item.source.name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(item.body + "\n", encoding="utf-8")
    return f"+ {dest.name}  <- {item.source.name}"


@dataclass
class BridgeResult:
    exported: int
    skipped: int
    inbox: Path | None
    messages: list[str]


def bridge_inbox(
    *,
    inbox: Path | None = None,
    out_dir: Path = DEFAULT_OUT,
    tickers: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = True,
) -> BridgeResult:
    """Copy earnings-scraper inbox transcripts into transcripts_raw/."""
    resolved_inbox = inbox or default_inbox()
    messages: list[str] = []
    exported = 0
    skipped_count = 0

    if resolved_inbox is None or not resolved_inbox.is_dir():
        if verbose:
            print(f"  ! inbox not found: {resolved_inbox}", file=sys.stderr)
        return BridgeResult(0, 0, resolved_inbox, messages)

    ticker_filter = {t.upper() for t in tickers} if tickers else set()
    files = sorted(p for p in resolved_inbox.glob("*.txt") if p.is_file())
    if verbose:
        print(f"Inbox:  {resolved_inbox}")
        print(f"Output: {out_dir}")
        if dry_run:
            print("(dry run — no files written)\n")

    for path in files:
        parsed = parse_inbox_file(path)
        if isinstance(parsed, SkipResult):
            skipped_count += 1
            msg = f"! skip {path.name}: {parsed.reason}"
            messages.append(msg)
            if verbose:
                print(f"  {msg}")
            continue
        if ticker_filter and parsed.ticker not in ticker_filter:
            continue
        msg = export_transcript(parsed, out_dir, force=force, dry_run=dry_run)
        messages.append(msg)
        if verbose:
            print(f"  {msg}")
        if msg.startswith("+") or msg.startswith("~"):
            exported += 1
        elif msg.startswith("="):
            skipped_count += 1

    if verbose:
        print(f"\nDone: {exported} exported, {skipped_count} skipped.")
    return BridgeResult(exported, skipped_count, resolved_inbox, messages)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export earnings-scraper inbox transcripts to transcripts_raw/."
    )
    ap.add_argument(
        "--inbox",
        type=Path,
        default=None,
        help="Scraper inbox directory (default: auto-detect Desktop earnings-scraper-main/inbox).",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Destination directory (default: {DEFAULT_OUT}).",
    )
    ap.add_argument("--ticker", action="append", default=[], help="Only export these tickers (repeatable).")
    ap.add_argument("--force", action="store_true", help="Overwrite existing destination files.")
    ap.add_argument("--dry-run", action="store_true", help="Print actions without writing files.")
    args = ap.parse_args()

    tickers = [t.upper() for t in args.ticker] if args.ticker else None
    result = bridge_inbox(
        inbox=args.inbox,
        out_dir=args.out,
        tickers=tickers,
        force=args.force,
        dry_run=args.dry_run,
        verbose=True,
    )
    if result.inbox is None or not result.inbox.is_dir():
        print(
            "Set EARNINGS_SCRAPER_INBOX or pass --inbox to your earnings-scraper inbox folder.",
            file=sys.stderr,
        )
        return 2
    if not list(result.inbox.glob("*.txt")):
        print(f"No .txt files in {result.inbox}")
        return 1
    if result.exported == 0 and result.skipped == 0 and tickers:
        print("Nothing matched your --ticker filter.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
