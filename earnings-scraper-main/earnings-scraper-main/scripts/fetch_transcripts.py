#!/usr/bin/env python3
"""Fetch earnings-call transcripts into inbox/ (ROIC.ai primary, SEC EDGAR fallback).

Like the Snowflake puller, this just fills ``inbox/`` with files so the exact
same coordinator crunch runs afterward — the network is only another way to fill
the inbox.

Primary source is the ROIC.ai transcript API (free tier: 5 req/min, 2 years of
history, all public companies). When ROIC has no transcript for a ticker/period
(404) or the period is outside the plan's history window (403), it falls back to
the company's most recent earnings 8-K (Item 2.02) exhibit on SEC EDGAR — that
gives the press release / prepared remarks, though usually not the live Q&A.

Setup
-----
    export ROIC_API_KEY=...        # get a free key at https://roic.ai
    # optional: export SEC_USER_AGENT="you (contact: you@example.com)"

Examples
--------
    # Latest call for one or more tickers
    python scripts/fetch_transcripts.py AAPL MSFT

    # A specific fiscal quarter
    python scripts/fetch_transcripts.py AAPL --year 2025 --quarter 3

    # The N most recent available quarters (uses the ROIC list endpoint)
    python scripts/fetch_transcripts.py AAPL --last 4

    # Every available quarter (bounded by the plan's history window)
    python scripts/fetch_transcripts.py AAPL --all

    # Bulk backfill a whole universe from a file (one ticker per line)
    python scripts/fetch_transcripts.py --tickers-file scripts/universe_overnight.txt --all --no-fallback

    # Skip the EDGAR fallback (ROIC only)
    python scripts/fetch_transcripts.py AAPL --no-fallback

After fetching, ask the agent (in Cursor chat) to "process the inbox".
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earnings_scraper import config  # noqa: E402
from earnings_scraper import edgar_fallback, roic_client  # noqa: E402


def _slug(text: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in text).strip("-").lower()
    while "--" in out:
        out = out.replace("--", "-")
    return out or "doc"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(dest: Path, header: dict[str, str], body: str, *, force: bool) -> bool:
    if not force:
        if dest.exists():
            print(f"  = exists, skip: {dest.name}")
            return False
        # Skip anything already extracted and archived by the coordinator, so a
        # re-run doesn't re-download a transcript that's already been processed.
        if (config.PROCESSED_DIR / dest.name).exists():
            print(f"  = already processed, skip: {dest.name}")
            return False
    head_lines = [f"# {k}: {v}" for k, v in header.items()]
    dest.write_text("\n".join(head_lines) + "\n\n" + body.strip() + "\n", encoding="utf-8")
    print(f"  + {dest.name}")
    return True


def _write_roic(t: roic_client.Transcript, ticker: str, inbox: Path, *, force: bool) -> bool:
    name = _slug(f"{ticker}_fy{t.year}_q{t.quarter}_earnings-call") + ".txt"
    header = {
        "company": ticker.upper(),
        "period": f"FY{t.year} Q{t.quarter}",
        "event": "earnings-call",
        "call_date": t.date,
        "source": "ROIC.ai earnings-call transcript API",
        "fetched": _now_iso(),
    }
    return _write(inbox / name, header, t.content, force=force)


def _write_edgar(r: edgar_fallback.EdgarResult, inbox: Path, *, force: bool) -> bool:
    name = _slug(f"{r.ticker}_{r.filing_date}_8k-earnings") + ".txt"
    header = {
        "company": r.ticker,
        "period": f"8-K filed {r.filing_date}",
        "event": "earnings-8k",
        "source": f"SEC EDGAR 8-K (Item 2.02) fallback — {r.source_url}",
        "accession": r.accession,
        "fetched": _now_iso(),
        "note": "Prepared remarks / press release; live Q&A typically not included.",
    }
    return _write(inbox / name, header, r.text, force=force)


def _targets(ticker: str, args) -> list[tuple[int, int]]:
    """Resolve the (year, quarter) pairs to fetch from ROIC for one ticker."""
    if args.year and args.quarter:
        return [(args.year, args.quarter)]
    if args.all:
        calls = roic_client.list_calls(ticker, limit=200)
        return [(int(c["year"]), int(c["quarter"])) for c in calls]
    if args.last:
        calls = roic_client.list_calls(ticker, limit=args.last)
        return [(int(c["year"]), int(c["quarter"])) for c in calls[: args.last]]
    return []  # empty => "latest" mode


def _try_fallback(ticker: str, inbox: Path, args, reason: str) -> bool:
    if args.no_fallback:
        print(f"    (fallback disabled; {reason})", file=sys.stderr)
        return False
    print(f"    ROIC miss ({reason}) — trying SEC EDGAR fallback...")
    try:
        result = edgar_fallback.fetch_latest_earnings_report(ticker)
    except edgar_fallback.EdgarError as e:
        print(f"    ! EDGAR fallback failed: {e}", file=sys.stderr)
        return False
    return _write_edgar(result, inbox, force=args.force)


def _fetch_ticker(ticker: str, inbox: Path, args) -> int:
    print(f"\n{ticker.upper()}:")
    fetched = 0
    try:
        targets = _targets(ticker, args)
    except roic_client.RoicError as e:
        print(f"  ! ROIC list failed: {e}", file=sys.stderr)
        return 1 if _try_fallback(ticker, inbox, args, f"list error {e.status}") else 0

    if not targets:  # latest mode
        try:
            t = roic_client.latest(ticker)
            if t.has_content:
                fetched += _write_roic(t, ticker, inbox, force=args.force)
            else:
                _try_fallback(ticker, inbox, args, "empty transcript")
        except roic_client.RoicError as e:
            if e.status in (403, 404):
                fetched += _try_fallback(ticker, inbox, args, f"HTTP {e.status}")
            else:
                print(f"  ! ROIC error: {e}", file=sys.stderr)
        return fetched

    single = len(targets) == 1
    for year, quarter in targets:
        try:
            t = roic_client.get_transcript(ticker, year, quarter)
            if t.has_content:
                fetched += _write_roic(t, ticker, inbox, force=args.force)
            else:
                print(f"  ! empty transcript for FY{year} Q{quarter}", file=sys.stderr)
        except roic_client.RoicError as e:
            if e.status == 403:
                # Older than the plan's history window. The list is newest-first,
                # so every remaining target is older too — stop this ticker.
                print(f"  . FY{year} Q{quarter} outside history window; stopping.", file=sys.stderr)
                break
            if e.status == 404:
                # A single explicit quarter can fall back to EDGAR's latest 8-K;
                # in a bulk pull a per-quarter miss is just skipped.
                if single:
                    fetched += _try_fallback(ticker, inbox, args, f"FY{year} Q{quarter} HTTP 404")
                else:
                    print(f"  ! no transcript for FY{year} Q{quarter}", file=sys.stderr)
                continue
            print(f"  ! ROIC error for FY{year} Q{quarter}: {e}", file=sys.stderr)
    return fetched


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fetch earnings transcripts into inbox/ (ROIC.ai + SEC EDGAR fallback)."
    )
    ap.add_argument("tickers", nargs="*", help="Ticker symbols, e.g. AAPL MSFT.")
    ap.add_argument("--tickers-file", metavar="PATH", help="Read tickers from a file (one per line; # comments ok).")
    ap.add_argument("--year", type=int, help="Fiscal year (requires --quarter).")
    ap.add_argument("--quarter", type=int, choices=[1, 2, 3, 4], help="Fiscal quarter 1-4.")
    ap.add_argument("--last", type=int, metavar="N", help="Fetch the N most recent quarters.")
    ap.add_argument("--all", action="store_true", help="Fetch every available quarter (bounded by plan history).")
    ap.add_argument("--no-fallback", action="store_true", help="Disable the SEC EDGAR fallback.")
    ap.add_argument("--force", action="store_true", help="Overwrite existing inbox files.")
    args = ap.parse_args()

    if bool(args.year) ^ bool(args.quarter):
        ap.error("--year and --quarter must be used together.")
    modes = [bool(args.all), bool(args.last), bool(args.year or args.quarter)]
    if sum(modes) > 1:
        ap.error("Choose only one of --all, --last, or --year/--quarter.")

    tickers = list(args.tickers)
    if args.tickers_file:
        for raw in Path(args.tickers_file).expanduser().read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                tickers.append(line)
    # De-dupe while preserving order.
    tickers = list(dict.fromkeys(t.upper() for t in tickers))
    if not tickers:
        ap.error("No tickers given (pass positional tickers and/or --tickers-file).")

    if not config.ROIC_API_KEY:
        print(
            "ROIC_API_KEY is unset and secrets/roic_api is empty — get a free key at "
            "https://roic.ai and put it in secrets/roic_api (or export ROIC_API_KEY).",
            file=sys.stderr,
        )
        return 2

    inbox = config.INBOX_DIR
    inbox.mkdir(parents=True, exist_ok=True)

    total = 0
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}]", end="", flush=True)
        try:
            total += _fetch_ticker(ticker, inbox, args)
        except Exception as e:  # noqa: BLE001 - one bad ticker must not kill an overnight run
            print(f"  !! unexpected error for {ticker}: {e}", file=sys.stderr)

    print(f"\nFetched {total} file(s) into {inbox}")
    if total:
        print("Next: in Cursor chat, ask the agent to 'process the inbox'.")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
