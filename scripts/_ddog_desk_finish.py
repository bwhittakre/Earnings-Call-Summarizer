"""Run DDOG Claims Desk finish after the FY panel is scored."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.earnings_monitor.onboard import run_desk_finish_after_panel  # noqa: E402


def main() -> int:
    steps = run_desk_finish_after_panel(
        repo_root=ROOT,
        ticker="DDOG",
        fiscal_period="FY2026-Q2",
        dry_run=False,
    )
    print(json.dumps(steps, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
