from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from src.export.confidence_reference_key import write_confidence_reference_key
from src.market.quarter_labels import quarter_sort_key
from src.schemas.models import EvidenceClaim, QuarterSummary

CSV_COLUMNS = [
    "summary_type",
    "company_name",
    "quarter",
    "what_happened",
    "positives",
    "negatives",
    "transcript_only_confidence_score",
    "confidence_score",
    "analysis",
]

DISPLAY_HEADERS = {
    "summary_type": "Summary Type",
    "company_name": "Company Name",
    "quarter": "Quarter",
    "what_happened": "What Happened",
    "positives": "Positives",
    "negatives": "Negatives",
    "transcript_only_confidence_score": "Document-Only Score",
    "confidence_score": "Confidence Score",
    "analysis": "Analysis",
}

EXCEL_COLUMN_WIDTHS = {
    "Summary Type": 16,
    "Company Name": 18,
    "Quarter": 18,
    "What Happened": 42,
    "Positives": 60,
    "Negatives": 60,
    "Document-Only Score": 18,
    "Confidence Score": 16,
    "Analysis": 80,
}

EXCEL_MAX_ROW_HEIGHT = 409.6
EXCEL_MAX_COLUMN_WIDTH = 255
MIN_DATA_ROW_HEIGHT = 42
POINTS_PER_WRAPPED_LINE = 15
ROW_HEIGHT_PADDING = 8

TABLE_COLUMN_COUNT = len(CSV_COLUMNS)
REFERENCE_KEY_SPACER_COLUMN = TABLE_COLUMN_COUNT + 1
REFERENCE_KEY_START_COLUMN = TABLE_COLUMN_COUNT + 2


def format_quarter_cell(quarter: str, call_date: str | None = None) -> str:
    if call_date:
        return f"{quarter}\nCall Date: {call_date}"
    return quarter


def format_what_happened(items: list[str]) -> str:
    return " & ".join(items)


def format_list(items: list[str]) -> str:
    return ", ".join(items)


def format_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def format_analysis_bullets(items: list[EvidenceClaim]) -> str:
    return "\n".join(f'• {item.claim} — "{item.excerpt}"' for item in items)


def format_analysis_csv(items: list[EvidenceClaim]) -> str:
    return " | ".join(f'{item.claim} — "{item.excerpt}"' for item in items)


def summary_to_row(summary: QuarterSummary) -> dict[str, str]:
    return {
        "summary_type": summary.summary_type,
        "company_name": summary.company_name,
        "quarter": format_quarter_cell(summary.quarter, summary.call_date),
        "what_happened": format_what_happened(summary.what_happened),
        "positives": format_list(summary.positives),
        "negatives": format_list(summary.negatives),
        "transcript_only_confidence_score": str(summary.transcript_only_confidence_score),
        "confidence_score": str(summary.confidence_score),
        "analysis": format_analysis_csv(summary.analysis),
    }


def summary_to_excel_row(summary: QuarterSummary) -> dict[str, str]:
    return {
        "Summary Type": summary.summary_type.title(),
        "Company Name": summary.company_name,
        "Quarter": format_quarter_cell(summary.quarter, summary.call_date),
        "What Happened": format_bullets(summary.what_happened),
        "Positives": format_bullets(summary.positives),
        "Negatives": format_bullets(summary.negatives),
        "Document-Only Score": str(summary.transcript_only_confidence_score),
        "Confidence Score": str(summary.confidence_score),
        "Analysis": format_analysis_bullets(summary.analysis),
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


def estimate_wrapped_line_count(value: object, column_width: float) -> int:
    text = str(value or "")
    if not text:
        return 1

    chars_per_line = max(8, int(column_width))
    wrapped_lines = 0
    for line in text.splitlines() or [""]:
        wrapped_lines += max(1, math.ceil(len(line) / chars_per_line))
    return wrapped_lines


def max_lines_at_max_height() -> int:
    return int(
        (EXCEL_MAX_ROW_HEIGHT - ROW_HEIGHT_PADDING) // POINTS_PER_WRAPPED_LINE
    )


def min_column_width_for_text(
    text: str,
    max_lines: int,
    min_width: int = 8,
    max_width: int = EXCEL_MAX_COLUMN_WIDTH,
) -> float:
    if not text.strip():
        return float(min_width)

    if estimate_wrapped_line_count(text, max_width) > max_lines:
        return float(max_width)

    low = min_width
    high = max_width
    while low < high:
        mid = (low + high) // 2
        if estimate_wrapped_line_count(text, mid) <= max_lines:
            high = mid
        else:
            low = mid + 1
    return float(low)


def compute_analysis_column_width(worksheet, analysis_column_index: int) -> float:
    default_width = EXCEL_COLUMN_WIDTHS["Analysis"]
    if worksheet.max_row < 2:
        return default_width

    max_lines = max_lines_at_max_height()
    required_width = default_width
    for row_index in range(2, worksheet.max_row + 1):
        cell_value = worksheet.cell(row=row_index, column=analysis_column_index).value
        if cell_value is None:
            continue
        required_width = max(
            required_width,
            min_column_width_for_text(str(cell_value), max_lines),
        )
    return min(required_width, float(EXCEL_MAX_COLUMN_WIDTH))


def estimate_row_height(worksheet, row_index: int, table_column_count: int) -> float:
    max_lines = 1
    for column_index in range(1, table_column_count + 1):
        column_letter = get_column_letter(column_index)
        column_width = worksheet.column_dimensions[column_letter].width or 12
        cell_value = worksheet.cell(row=row_index, column=column_index).value
        max_lines = max(
            max_lines,
            estimate_wrapped_line_count(cell_value, column_width),
        )

    estimated_height = (max_lines * POINTS_PER_WRAPPED_LINE) + ROW_HEIGHT_PADDING
    return min(
        max(float(MIN_DATA_ROW_HEIGHT), estimated_height),
        EXCEL_MAX_ROW_HEIGHT,
    )


def write_csv(rows: Sequence[QuarterSummary], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(summary_to_row(row))


def batch_result_to_excel_row(result) -> dict[str, str]:
    from src.batch.models import BatchQuarterResult

    if not isinstance(result, BatchQuarterResult):
        raise TypeError("batch_result_to_excel_row expects BatchQuarterResult")

    if result.status == "success" and result.summary is not None:
        return summary_to_excel_row(result.summary)

    call_date = (
        result.knowledge_cutoff.isoformat() if result.knowledge_cutoff else None
    )
    raw_error = result.error_message or result.last_error or "unknown error"
    if result.status == "skipped":
        what_happened = raw_error
        if not what_happened.startswith("SKIPPED after 2 attempts"):
            what_happened = f"SKIPPED after 2 attempts: {what_happened}"
    else:
        what_happened = raw_error
        if not what_happened.startswith("EDGAR fetch failed"):
            what_happened = f"EDGAR fetch failed: {what_happened}"
    analysis_note = ""
    if result.manifest_path:
        analysis_note = f"Manifest: {result.manifest_path}"
    return {
        "Summary Type": "Quarter",
        "Company Name": "",
        "Quarter": format_quarter_cell(result.quarter_label, call_date),
        "What Happened": what_happened,
        "Positives": "",
        "Negatives": "",
        "Document-Only Score": "",
        "Confidence Score": "",
        "Analysis": analysis_note,
    }


FAILED_ROW_FILL = PatternFill("solid", fgColor="FFC7CE")
SKIPPED_ROW_FILL = PatternFill("solid", fgColor="FFEB9C")
BACKFILLED_ROW_FILL = PatternFill("solid", fgColor="DDEBF7")

CONFIDENCE_LANE_NOTE = (
    "Confidence Score uses Edgar documents only; transcript columns are informational."
)


def _apply_batch_row_highlight(
    worksheet,
    row_index: int,
    headers: list[str],
    status: str,
    *,
    backfilled_from_analysis: list[str] | None = None,
) -> None:
    if status in {"failed", "skipped"}:
        fill = FAILED_ROW_FILL if status == "failed" else SKIPPED_ROW_FILL
        for header in ("Quarter", "What Happened"):
            column_index = headers.index(header) + 1
            worksheet.cell(row=row_index, column=column_index).fill = fill
        return
    if backfilled_from_analysis:
        for header in ("Positives", "Negatives"):
            if header not in headers:
                continue
            column_index = headers.index(header) + 1
            worksheet.cell(row=row_index, column=column_index).fill = BACKFILLED_ROW_FILL


def _write_skipped_summary_sheet(workbook, results) -> None:
    from src.batch.models import BatchQuarterResult

    summary_rows = [
        result
        for result in results
        if isinstance(result, BatchQuarterResult)
        and result.status in {"failed", "skipped"}
    ]
    if not summary_rows:
        return

    summary_rows.sort(key=lambda item: quarter_sort_key(item.quarter_label))
    sheet = workbook.create_sheet("Skipped Summary")
    headers = ["Quarter", "Status", "Attempts", "Error", "Manifest"]
    sheet.append(headers)

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for result in summary_rows:
        sheet.append(
            [
                result.quarter_label,
                result.status,
                result.attempts,
                result.last_error or result.error_message or "",
                str(result.manifest_path) if result.manifest_path else "",
            ]
        )
        row_index = sheet.max_row
        fill = FAILED_ROW_FILL if result.status == "failed" else SKIPPED_ROW_FILL
        for column_index in range(1, len(headers) + 1):
            sheet.cell(row=row_index, column=column_index).fill = fill

    for column_index, header in enumerate(headers, start=1):
        sheet.column_dimensions[get_column_letter(column_index)].width = max(
            len(header) + 2,
            18 if header == "Error" else 14,
        )
    sheet.freeze_panes = "A2"


def _insert_sheet_note(worksheet, note: str, column_count: int) -> None:
    has_content = (
        worksheet.max_row > 1
        or worksheet.cell(row=1, column=1).value is not None
    )
    if has_content:
        worksheet.insert_rows(1)
    worksheet.merge_cells(
        start_row=1,
        start_column=1,
        end_row=1,
        end_column=column_count,
    )
    cell = worksheet.cell(row=1, column=1, value=note)
    cell.alignment = Alignment(wrap_text=True, vertical="center")
    cell.font = Font(italic=True, color="444444")
    worksheet.row_dimensions[1].height = 28


def _enrichment_to_row(result) -> dict[str, str]:
    from src.enrichment.models import EnrichmentResult

    if not isinstance(result, EnrichmentResult):
        raise TypeError("_enrichment_to_row expects EnrichmentResult")
    source = "missing"
    if result.availability == "found":
        source = result.notes.split(";")[0].replace("Source: ", "").strip() or "found"
    return {
        "Quarter": result.quarter,
        "Transcript Source": source,
        "Positives (transcript)": format_bullets([item.claim for item in result.positives]),
        "Negatives (transcript)": format_bullets([item.claim for item in result.negatives]),
        "Notes": result.notes,
    }


def _write_transcript_enrichment_sheet(workbook, enrichment_results) -> None:
    from src.enrichment.models import EnrichmentResult

    if not enrichment_results:
        return
    headers = [
        "Quarter",
        "Transcript Source",
        "Positives (transcript)",
        "Negatives (transcript)",
        "Notes",
    ]
    sheet = workbook.create_sheet("Transcript Enrichment")
    _insert_sheet_note(sheet, CONFIDENCE_LANE_NOTE, len(headers))
    sheet.append(headers)
    for result in enrichment_results:
        if not isinstance(result, EnrichmentResult):
            continue
        row = _enrichment_to_row(result)
        sheet.append([row[header] for header in headers])
    populate_enrichment_sheet_body(sheet, headers)


def populate_enrichment_sheet_body(worksheet, headers: list[str]) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    body_alignment = Alignment(vertical="top", wrap_text=True)
    centered_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    header_row = 2
    for cell in worksheet[header_row]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment

    centered_columns = {"Quarter", "Transcript Source"}
    for row in worksheet.iter_rows(min_row=header_row + 1):
        for cell in row:
            header = worksheet.cell(row=header_row, column=cell.column).value
            cell.alignment = (
                centered_alignment if header in centered_columns else body_alignment
            )

    for column_index, header in enumerate(headers, start=1):
        column_letter = get_column_letter(column_index)
        width = {
            "Quarter": 18,
            "Transcript Source": 20,
            "Positives (transcript)": 60,
            "Negatives (transcript)": 60,
            "Notes": 40,
        }.get(header, 18)
        worksheet.column_dimensions[column_letter].width = width

    worksheet.row_dimensions[header_row].height = 28
    last_data_row = worksheet.max_row
    for row_index in range(header_row + 1, last_data_row + 1):
        worksheet.row_dimensions[row_index].height = estimate_row_height(
            worksheet,
            row_index,
            len(headers),
        )
    worksheet.freeze_panes = "A3"
    worksheet.auto_filter.ref = (
        f"A{header_row}:{get_column_letter(len(headers))}{last_data_row}"
    )


def write_batch_excel(results, output_path: Path, enrichment_results=None) -> None:
    from src.batch.models import BatchQuarterResult

    sorted_results = sorted(
        results,
        key=lambda item: quarter_sort_key(item.quarter_label),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Batch Backtest"

    headers = [DISPLAY_HEADERS[column] for column in CSV_COLUMNS]
    _insert_sheet_note(worksheet, CONFIDENCE_LANE_NOTE, len(headers))
    worksheet.append(headers)

    result_by_row: dict[int, BatchQuarterResult] = {}
    for result in sorted_results:
        if not isinstance(result, BatchQuarterResult):
            raise TypeError("write_batch_excel expects BatchQuarterResult items")
        row = batch_result_to_excel_row(result)
        worksheet.append([row[header] for header in headers])
        result_by_row[worksheet.max_row] = result

    populate_excel_sheet_body(worksheet, headers, header_row=2)
    for row_index, result in result_by_row.items():
        _apply_batch_row_highlight(
            worksheet,
            row_index,
            headers,
            result.status,
            backfilled_from_analysis=result.backfilled_from_analysis,
        )

    _write_skipped_summary_sheet(workbook, sorted_results)
    if enrichment_results:
        sorted_enrichment = sorted(
            enrichment_results,
            key=lambda item: quarter_sort_key(item.quarter),
        )
        _write_transcript_enrichment_sheet(workbook, sorted_enrichment)
    workbook.save(output_path)


def populate_excel_sheet(worksheet, rows: Sequence[QuarterSummary]) -> None:
    headers = [DISPLAY_HEADERS[column] for column in CSV_COLUMNS]
    worksheet.append(headers)

    for summary in rows:
        excel_row = summary_to_excel_row(summary)
        worksheet.append([excel_row[header] for header in headers])

    populate_excel_sheet_body(worksheet, headers)


def populate_excel_sheet_body(worksheet, headers: list[str], *, header_row: int = 1) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    body_alignment = Alignment(vertical="top", wrap_text=True)
    centered_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for cell in worksheet[header_row]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment

    centered_columns = {
        "Summary Type",
        "Company Name",
        "Quarter",
        "Document-Only Score",
        "Confidence Score",
    }
    for row in worksheet.iter_rows(min_row=header_row + 1):
        for cell in row:
            header = worksheet.cell(row=header_row, column=cell.column).value
            cell.alignment = (
                centered_alignment if header in centered_columns else body_alignment
            )

    analysis_column_index = headers.index("Analysis") + 1
    for column_index, header in enumerate(headers, start=1):
        column_letter = get_column_letter(column_index)
        if header == "Analysis":
            continue
        worksheet.column_dimensions[column_letter].width = EXCEL_COLUMN_WIDTHS[header]

    analysis_letter = get_column_letter(analysis_column_index)
    worksheet.column_dimensions[analysis_letter].width = compute_analysis_column_width(
        worksheet,
        analysis_column_index,
    )

    worksheet.row_dimensions[header_row].height = 28
    last_data_row = worksheet.max_row
    for row_index in range(header_row + 1, last_data_row + 1):
        worksheet.row_dimensions[row_index].height = estimate_row_height(
            worksheet,
            row_index,
            TABLE_COLUMN_COUNT,
        )

    write_confidence_reference_key(
        worksheet,
        start_column=REFERENCE_KEY_START_COLUMN,
        table_last_row=last_data_row,
        spacer_column=REFERENCE_KEY_SPACER_COLUMN,
    )

    freeze_row = header_row + 1
    worksheet.freeze_panes = f"A{freeze_row}"
    worksheet.auto_filter.ref = (
        f"A{header_row}:{get_column_letter(TABLE_COLUMN_COUNT)}{last_data_row}"
    )


def group_rows_by_company(rows: Sequence[QuarterSummary]) -> dict[str, list[QuarterSummary]]:
    grouped: dict[str, list[QuarterSummary]] = {}
    for row in rows:
        grouped.setdefault(row.company_name, []).append(row)
    return grouped


def write_excel(rows: Sequence[QuarterSummary], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)

    existing_titles: set[str] = set()
    grouped_rows = group_rows_by_company(rows)
    if not grouped_rows:
        worksheet = workbook.create_sheet("Earnings Summary")
        populate_excel_sheet(worksheet, [])
    else:
        for company_name, company_rows in grouped_rows.items():
            sheet_title = sanitize_sheet_title(company_name, existing_titles)
            worksheet = workbook.create_sheet(sheet_title)
            populate_excel_sheet(worksheet, company_rows)

    workbook.save(output_path)


def write_output(rows: Sequence[QuarterSummary], output_path: Path) -> None:
    if output_path.suffix.lower() == ".xlsx":
        write_excel(rows, output_path)
        return
    write_csv(rows, output_path)
