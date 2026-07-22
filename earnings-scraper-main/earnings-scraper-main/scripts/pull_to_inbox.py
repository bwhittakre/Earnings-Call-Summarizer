#!/usr/bin/env python3
"""FUTURE: pull LSEG StreetEvents transcripts from Snowflake into inbox/.

Status: STUB. The Snowflake account is not yet entitled to a StreetEvents
Transcripts & Briefs share (probed 2026-07-08 — only estimates/factor data is
available). Once the share is provisioned, fill in ``_query_transcripts`` and set
``EARNINGS_LSEG_TRANSCRIPT_DB`` (see config.py / env_setup.sh).

Design: this writes each transcript to ``inbox/`` as a file (with a normalized
name), so it feeds the EXACT SAME coordinator crunch as manually-dropped reports.
The warehouse is just another way to fill the inbox.

    source scripts/env_setup.sh
    python scripts/pull_to_inbox.py --since 2026-07-01
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earnings_scraper import config  # noqa: E402


def _query_transcripts(conn, since: str):
    """Return rows of (ticker, period, event_type, event_datetime, status, text).

    TODO(share-lands): implement against the StreetEvents transcript view once
    the share is provisioned. Expected shape (confirm real columns via a SHOW
    COLUMNS probe): a transcript id, RIC/ticker, event datetime, a
    preliminary/final status, and the transcript body (inline text or a document
    pointer to fetch). Filter by ``event_datetime >= %(since)s`` and
    (optionally) ``status = 'Preliminary'`` for the freshest cut.
    """
    raise NotImplementedError(
        "No transcript share is provisioned yet. Fill in _query_transcripts and "
        "EARNINGS_LSEG_TRANSCRIPT_DB once the StreetEvents share lands."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull LSEG transcripts into inbox/ (future).")
    ap.add_argument("--since", required=True, help="ISO date lower bound, e.g. 2026-07-01.")
    args = ap.parse_args()

    if not config.LSEG_TRANSCRIPT_DB:
        print(
            "EARNINGS_LSEG_TRANSCRIPT_DB is unset — no transcript share provisioned yet.\n"
            "This puller is a stub until the LSEG StreetEvents share is granted to the account.",
            file=sys.stderr,
        )
        return 2

    from earnings_scraper.snowflake_io import get_connection  # noqa: E402

    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection(database=config.LSEG_TRANSCRIPT_DB) as conn:
        rows = _query_transcripts(conn, args.since)
        # TODO(share-lands): for each row, write body to inbox/<slug>.txt and set
        # a sidecar or filename encoding (ticker, period, event) for the agent.
        _ = rows
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
