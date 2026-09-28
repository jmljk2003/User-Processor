"""Excel workbook creation, sheet-name safety, deduplication, and validation."""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from models import ProcessingIssue, WorkbookRecord


HEADERS = [
    "User Name",
    "User Role Name",
    "Email",
    "MFA",
    "Review Required",
    "Source PDF",
    "Page",
]
ISSUE_HEADERS = ["Source PDF", "Page", "Issue"]
INVALID_SHEET_CHARS = re.compile(r"[\\/*?:\[\]\x00-\x1f]")


def safe_sheet_name(location: str, used_names: set[str]) -> str:
    base = INVALID_SHEET_CHARS.sub("-", location).strip().strip("'") or "UNRESOLVED"
    base = base[:31]
    candidate = base
    suffix_number = 2
    used_lower = {name.casefold() for name in used_names}
    while candidate.casefold() in used_lower:
        suffix = f" ({suffix_number})"
        candidate = f"{base[: 31 - len(suffix)]}{suffix}"
        suffix_number += 1
    used_names.add(candidate)
    return candidate


def deduplicate(records: list[WorkbookRecord]) -> list[WorkbookRecord]:
    unique: OrderedDict[tuple[object, ...], WorkbookRecord] = OrderedDict()
    for record in records:
        key = (
            record.location,
            record.user_name,
            record.user_role_name,
            record.email,
            record.mfa,
            record.source_pdf,
            record.page,
        )
        if key not in unique:
            unique[key] = record
        elif record.review_required == "YES":
            unique[key].review_required = "YES"
    return list(unique.values())


def _format_sheet(worksheet, headers: list[str], widths: list[float]) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def _force_text_cells(worksheet, row_number: int, columns: list[int]) -> None:
    """Prevent extracted values beginning with '=' from becoming Excel formulas."""
    for column in columns:
        cell = worksheet.cell(row=row_number, column=column)
        if cell.value is not None:
            cell.data_type = "s"


def write_workbook(
    records: list[WorkbookRecord], issues: list[ProcessingIssue], output_path: Path
) -> None:
    records = deduplicate(records)
    grouped: OrderedDict[str, list[WorkbookRecord]] = OrderedDict()
    display_names: dict[str, str] = {}
    for record in records:
        display_name = " ".join((record.location or "UNRESOLVED").split())
        location_key = display_name.casefold()
        display_names.setdefault(location_key, display_name)
        grouped.setdefault(location_key, []).append(record)

    workbook = Workbook()
    workbook.remove(workbook.active)
    used_names: set[str] = set()

    for location_key, location_records in grouped.items():
        worksheet = workbook.create_sheet(
            safe_sheet_name(display_names[location_key], used_names)
        )
        worksheet.append(HEADERS)
        for record in location_records:
            worksheet.append(
                [
                    record.user_name,
                    record.user_role_name,
                    record.email,
                    record.mfa,
                    record.review_required,
                    record.source_pdf,
                    record.page,
                ]
            )
            _force_text_cells(worksheet, worksheet.max_row, [1, 2, 3, 4, 5, 6])
        _format_sheet(worksheet, HEADERS, [24, 25, 35, 14, 18, 32, 10])

    if issues:
        worksheet = workbook.create_sheet(safe_sheet_name("PROCESSING ISSUES", used_names))
        worksheet.append(ISSUE_HEADERS)
        for issue in issues:
            worksheet.append([issue.source_pdf, issue.page or "", issue.issue])
            _force_text_cells(worksheet, worksheet.max_row, [1, 3])
        _format_sheet(worksheet, ISSUE_HEADERS, [32, 10, 34])

    if not workbook.worksheets:
        worksheet = workbook.create_sheet("NO DATA")
        worksheet.append(HEADERS)
        _format_sheet(worksheet, HEADERS, [24, 25, 35, 14, 18, 32, 10])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def validate_workbook(output_path: Path, records: list[WorkbookRecord]) -> None:
    if any(not record.location for record in records):
        raise ValueError("Every extracted record must belong to a location or UNRESOLVED")

    workbook = load_workbook(output_path, read_only=True, data_only=True)
    try:
        if not workbook.sheetnames:
            raise ValueError("Generated workbook contains no worksheets")
        for worksheet in workbook.worksheets:
            if worksheet.title in {"PROCESSING ISSUES", "NO DATA"}:
                continue
            actual_headers = [cell.value for cell in next(worksheet.iter_rows(max_row=1))]
            if actual_headers != HEADERS:
                raise ValueError(f"Worksheet '{worksheet.title}' has invalid columns")
    finally:
        workbook.close()
