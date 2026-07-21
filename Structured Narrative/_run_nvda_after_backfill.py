#!/usr/bin/env python3
"""Wait for the MSFT/AAPL/AMZN backfill PID, then score NVDA historical transcripts."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PY = sys.executable


def pid_alive(pid: int) -> bool:
    # Windows: tasklist; also works if process already gone.
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in (out.stdout or "")
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-pid", type=int, required=True)
    ap.add_argument("--poll-seconds", type=int, default=60)
    args = ap.parse_args()

    print(f"Waiting for PID {args.wait_pid} to finish before NVDA backfill…", flush=True)
    while pid_alive(args.wait_pid):
        time.sleep(args.poll_seconds)
        print(f"  still waiting on {args.wait_pid}…", flush=True)

    print("Prior backfill finished — starting NVDA.", flush=True)
    cmd = [
        PY,
        str(HERE / "_run_historical_backfill.py"),
        "NVDA",
    ]
    print(">>>", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=REPO).returncode


if __name__ == "__main__":
    raise SystemExit(main())
