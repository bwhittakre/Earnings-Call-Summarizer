#!/usr/bin/env python3
"""Audit batch Excel output for blank positives/negatives and evidence drop rates."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook

from src.paths import EVIDENCE_AUDIT_DIR
from src.scoring.analysis_score import parse_analysis_weight


def _parse_quarter_cell(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.splitlines()[0].strip()


def _latest_audit_for_label(label_prefix: str) -> dict | None:
    pattern = re.compile(re.escape(label_prefix.replace("/", "_")) + r".*\.json$")
    candidates = sorted(
        (
            path
            for path in EVIDENCE_AUDIT_DIR.glob("*.json")
            if pattern.search(path.name)
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    return json.loads(candidates[0].read_text(encoding="utf-8"))


def audit_workbook(workbook_path: Path, output_csv: Path | None) -> list[dict]:
    workbook = load_workbook(workbook_path, data_only=True)
    sheet = workbook["Batch Backtest"] if "Batch Backtest" in workbook.sheetnames else workbook.active
    header_row = 1
    first_cell = sheet.cell(header_row, 1).value
    if first_cell and "Confidence Score uses Edgar" in str(first_cell):
        header_row = 2
    headers = [cell.value for cell in sheet[header_row]]
    col = {header: index + 1 for index, header in enumerate(headers) if header}

    rows: list[dict] = []
    for row_index in range(header_row + 1, sheet.max_row + 1):
        quarter = _parse_quarter_cell(sheet.cell(row_index, col["Quarter"]).value)
        positives = sheet.cell(row_index, col["Positives"]).value
        negatives = sheet.cell(row_index, col["Negatives"]).value
        analysis = sheet.cell(row_index, col["Analysis"]).value
        confidence = sheet.cell(row_index, col["Confidence Score"]).value

        pos_blank = not positives or not str(positives).strip()
        neg_blank = not negatives or not str(negatives).strip()
        analysis_text = str(analysis or "")
        weighted_bullets = sum(
            1
            for line in analysis_text.splitlines()
            if parse_analysis_weight(line.lstrip("• ").split(" — ")[0]) is not None
        )
        analysis_thin = weighted_bullets < 4

        audit = _latest_audit_for_label(f"{quarter}") or _latest_audit_for_label(
            quarter.replace("-", "_")
        )
        dropped_by_field: dict[str, int] = {}
        if audit:
            for entry in audit.get("dropped", []):
                field = entry.get("field", "unknown")
                dropped_by_field[field] = dropped_by_field.get(field, 0) + 1

        rows.append(
            {
                "quarter": quarter,
                "confidence_score": confidence,
                "blank_positives": pos_blank,
                "blank_negatives": neg_blank,
                "analysis_weighted_bullets": weighted_bullets,
                "thin_analysis": analysis_thin,
                "dropped_positives": dropped_by_field.get("positives", 0),
                "dropped_negatives": dropped_by_field.get("negatives", 0),
                "dropped_analysis": dropped_by_field.get("analysis", 0),
                "backfilled_from_analysis": ",".join(
                    audit.get("backfilled_from_analysis", [])
                )
                if audit
                else "",
            }
        )

    if output_csv:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with output_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
            writer.writeheader()
            writer.writerows(rows)

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit batch Excel quality metrics")
    parser.add_argument("workbook", type=Path, help="Path to batch .xlsx file")
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="Optional CSV summary output path",
    )
    args = parser.parse_args()

    rows = audit_workbook(args.workbook, args.output_csv)
    total = len(rows)
    blank_pos = sum(1 for row in rows if row["blank_positives"])
    blank_neg = sum(1 for row in rows if row["blank_negatives"])
    thin = sum(1 for row in rows if row["thin_analysis"])

    print(f"Quarters audited: {total}")
    print(f"Blank positives: {blank_pos}/{total}")
    print(f"Blank negatives: {blank_neg}/{total}")
    print(f"Thin analysis (<4 weighted bullets): {thin}/{total}")
    if args.output_csv:
        print(f"Wrote {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
