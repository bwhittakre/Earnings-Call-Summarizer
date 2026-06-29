#!/usr/bin/env python3
"""Thin wrapper for long-running historical batch backtests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import build_parser, configure_logging, main  # noqa: E402


def run() -> int:
    configure_logging()
    parser = build_parser()
    if "--batch" not in sys.argv:
        sys.argv.insert(1, "--batch")
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
