from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Sequence, Union

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from src.schemas.models import QuarterSummary, RollupSummary

SummaryRow = Union[QuarterSummary, RollupSummary]

CSV_COLUMNS = [
    "summary_type",
    "company_name",
    "quarter",
    "what_happened",
    "positives",
    "negatives",
    "confidence",
]

DISPLAY_HEADERS = {
    "summary_type": "Summary Type",
    "company_name": "Company Name",
    "quarter": "Quarter",
    "what_happened": "What Happened",
    "positives": "Positives",
    "negatives": "Negatives",
    "confidence": "Confidence",
}

EXCEL_COLUMN_WIDTHS = {
    "Summary Type": 16,
    "Company Name": 18,
    "Quarter": 18,
    "What Happened": 42,
    "Positives": 60,
    "Negatives": 60,
    "Confidence": 14,
}

EXCEL_MAX_ROW_HEIGHT = 409
MIN_DATA_ROW_HEIGHT = 42
POINTS_PER_WRAPPED_LINE = 15
ROW_HEIGHT_PADDING = 8


def format_what_happened(items: list[str]) -> str:
    return " & ".join(items)


def format_list(items: list[str]) -> str:
    return ", ".join(items)


def format_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def summary_to_row(summary: SummaryRow) -> dict[str, str]:
    return {
        "summary_type": summary.summary_type,
        "company_name": summary.company_name,
        "quarter": summary.quarter,
        "what_happened": format_what_happened(summary.what_happened),
        "positives": format_list(summary.positives),
        "negatives": format_list(summary.negatives),
        "confidence": summary.confidence,
    }


def summary_to_excel_row(summary: SummaryRow) -> dict[str, str]:
    return {
        "Summary Type": summary.summary_type.title(),
        "Company Name": summary.company_name,
        "Quarter": summary.quarter,
        "What Happened": format_bullets(summary.what_happened),
        "Positives": format_bullets(summary.positives),
        "Negatives": format_bullets(summary.negatives),
        "Confidence": summary.confidence,
    }


def sanitize_sheet_title(title: str, existing_titles: set[str]) -> str:
    sanitized = re.sub(r"[\[\]\:\*\?\/\\]", "", title).strip()
    if not sanitized:
        sanitized = "Company"
    sanitized = sanitized[:31]

    candidate = sanitized
    counter = 2
    while candidate in existing_titles:
        suffix = f" {counter}"
        candidate = f"{sanitized[:31 - len(suffix)]}{suffix}"
        counter += 1
    existing_titles.add(candidate)
    return candidate


def table_name_for_sheet(sheet_title: str, index: int) -> str:
    base = re.sub(r"\W+", "_", sheet_title).strip("_")
    if not base:
        base = "Company"
    if not base[0].isalpha():
        base = f"Company_{base}"
    return f"{base}_Summary_{index}"


def estimate_wrapped_line_count(value: object, column_width: float) -> int:
    text = str(value or "")
    if not text:
        return 1

    chars_per_line = max(8, int(column_width))
    wrapped_lines = 0
    for line in text.splitlines() or [""]:
        wrapped_lines += max(1, math.ceil(len(line) / chars_per_line))
    return wrapped_lines


def estimate_row_height(worksheet, row_index: int) -> int:
    max_lines = 1
    for column_index in range(1, worksheet.max_column + 1):
        column_letter = get_column_letter(column_index)
        column_width = worksheet.column_dimensions[column_letter].width or 12
        cell_value = worksheet.cell(row=row_index, column=column_index).value
        max_lines = max(
            max_lines,
            estimate_wrapped_line_count(cell_value, column_width),
        )

    estimated_height = (max_lines * POINTS_PER_WRAPPED_LINE) + ROW_HEIGHT_PADDING
    return min(max(MIN_DATA_ROW_HEIGHT, estimated_height), EXCEL_MAX_ROW_HEIGHT)


def write_csv(rows: Sequence[SummaryRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(summary_to_row(row))


def populate_excel_sheet(worksheet, rows: Sequence[SummaryRow], table_name: str) -> None:
    headers = [DISPLAY_HEADERS[column] for column in CSV_COLUMNS]
    worksheet.append(headers)

    for summary in rows:
        excel_row = summary_to_excel_row(summary)
        worksheet.append([excel_row[header] for header in headers])

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    body_alignment = Alignment(vertical="top", wrap_text=True)
    centered_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment

    centered_columns = {"Summary Type", "Company Name", "Quarter", "Confidence"}
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            header = worksheet.cell(row=1, column=cell.column).value
            cell.alignment = (
                centered_alignment if header in centered_columns else body_alignment
            )

    for column_index, header in enumerate(headers, start=1):
        column_letter = get_column_letter(column_index)
        worksheet.column_dimensions[column_letter].width = EXCEL_COLUMN_WIDTHS[header]

    worksheet.row_dimensions[1].height = 28
    for row_index in range(2, worksheet.max_row + 1):
        worksheet.row_dimensions[row_index].height = estimate_row_height(
            worksheet,
            row_index,
        )

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions

    table_ref = f"A1:{get_column_letter(worksheet.max_column)}{worksheet.max_row}"
    table = Table(displayName=table_name, ref=table_ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    worksheet.add_table(table)


def group_rows_by_company(rows: Sequence[SummaryRow]) -> dict[str, list[SummaryRow]]:
    grouped: dict[str, list[SummaryRow]] = {}
    for row in rows:
        grouped.setdefault(row.company_name, []).append(row)
    return grouped


def write_excel(rows: Sequence[SummaryRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)

    existing_titles: set[str] = set()
    grouped_rows = group_rows_by_company(rows)
    if not grouped_rows:
        worksheet = workbook.create_sheet("Earnings Summary")
        populate_excel_sheet(worksheet, [], "EarningsSummary_1")
    else:
        for index, (company_name, company_rows) in enumerate(grouped_rows.items(), start=1):
            sheet_title = sanitize_sheet_title(company_name, existing_titles)
            worksheet = workbook.create_sheet(sheet_title)
            populate_excel_sheet(
                worksheet,
                company_rows,
                table_name_for_sheet(sheet_title, index),
            )

    workbook.save(output_path)


def write_output(rows: Sequence[SummaryRow], output_path: Path) -> None:
    if output_path.suffix.lower() == ".xlsx":
        write_excel(rows, output_path)
        return
    write_csv(rows, output_path)
