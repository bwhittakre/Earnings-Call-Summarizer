#!/usr/bin/env python3
"""Drop earnings-call reports into the inbox for the coordinator to crunch.

This is the manual front door. Copy (or move) one or more report files into
``inbox/``, optionally normalizing the filename to ``<company>_<period>_<event>``
so the coordinator can read company/period straight off the name.

Examples
--------
    # Copy a couple of PDFs as-is
    python scripts/stage_inbox.py ~/Downloads/AAPL-Q3.pdf ~/Downloads/MSFT-Q3.pdf

    # Normalize the name from metadata
    python scripts/stage_inbox.py ~/Downloads/apple.pdf \
        --company AAPL --period FY2025Q1 --event earnings-call

    # Pull every PDF/txt out of a folder
    python scripts/stage_inbox.py ~/Downloads/earnings/ --move

After staging, ask the agent (in Cursor chat) to "process the inbox" — it acts as
the coordinator: runs grounded extraction via ``create_extraction_graph`` and
joins each source to the projects described in ``projects.yaml``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INBOX = Path(__file__).resolve().parents[1] / "inbox"
SUPPORTED = {".pdf", ".txt", ".md", ".html", ".htm", ".xml"}


def _slug(text: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in text).strip("-").lower()
    while "--" in out:
        out = out.replace("--", "-")
    return out or "doc"


def _expand(inputs: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED))
        elif p.is_file():
            files.append(p)
        else:
            print(f"  ! skip (not found): {p}", file=sys.stderr)
    return files


def _dest_name(src: Path, company: str, period: str, event: str) -> str:
    if company or period or event:
        parts = [p for p in (company, period, event or "earnings-call") if p]
        return f"{_slug('_'.join(parts))}{src.suffix.lower()}"
    return src.name


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage earnings reports into inbox/.")
    ap.add_argument("inputs", nargs="+", help="Files or directories to stage.")
    ap.add_argument("--company", default="", help="Ticker/company, e.g. AAPL.")
    ap.add_argument("--period", default="", help="Fiscal period, e.g. FY2025Q1.")
    ap.add_argument("--event", default="", help="Event type (default earnings-call).")
    ap.add_argument("--move", action="store_true", help="Move instead of copy.")
    args = ap.parse_args()

    INBOX.mkdir(parents=True, exist_ok=True)
    files = _expand(args.inputs)
    if not files:
        print("Nothing to stage.", file=sys.stderr)
        return 1

    staged = 0
    for src in files:
        dest = INBOX / _dest_name(src, args.company, args.period, args.event)
        if dest.exists():
            print(f"  = exists, skip: {dest.name}")
            continue
        (shutil.move if args.move else shutil.copy2)(str(src), str(dest))
        print(f"  + {dest.name}")
        staged += 1

    print(f"\nStaged {staged} file(s) into {INBOX}")
    print("Next: in Cursor chat, ask the agent to 'process the inbox'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
