"""Rebuild narrative_signal_eval.html with current rank_ic_html.py (dual-mode Jackknife)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SN = REPO / "Structured Narrative"
sys.path.insert(0, str(SN))

from rank_ic_html import build_rank_ic_report_html  # noqa: E402


def main() -> None:
    html_path = SN / "output" / "cross_company" / "reports" / "narrative_signal_eval.html"
    json_path = SN / "output" / "cross_company" / "json" / "narrative_signal_eval.json"
    jack_path = SN / "output" / "cross_company" / "csv" / "narrative_signal_eval_jackknife.csv"

    print("Reading HTML...", flush=True)
    text = html_path.read_text(encoding="utf-8")
    print(f"len={len(text)}", flush=True)
    match = re.search(r"const DATA = (\{.*?\});\r?\nconst SECTOR_PRESETS", text, re.S)
    if not match:
        raise SystemExit("DATA payload not found in existing HTML")
    print("Parsing DATA JSON...", flush=True)
    data = json.loads(match.group(1))
    print(
        "period_ics",
        len(data.get("period_ics") or []),
        "company_period",
        len(data.get("company_period") or []),
        flush=True,
    )
    report = json.loads(json_path.read_text(encoding="utf-8"))
    jack_rows = json.loads(pd.read_csv(jack_path).to_json(orient="records"))
    report["jackknife"] = jack_rows
    print("jackknife rows", len(jack_rows), flush=True)
    print("Building HTML...", flush=True)
    out = build_rank_ic_report_html(
        report,
        period_ics=data.get("period_ics") or [],
        company_period=data.get("company_period") or [],
    )
    html_path.write_text(out, encoding="utf-8")
    print("Wrote", html_path, "bytes", html_path.stat().st_size, flush=True)
    if 'data-jk-mode="book"' not in out or "recomputeSelectionJackknife" not in out:
        raise SystemExit("dual-mode markers missing from rebuilt HTML")
    print("OK dual-mode markers present", flush=True)


if __name__ == "__main__":
    main()
