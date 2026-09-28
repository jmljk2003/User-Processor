"""Command-line entry point for the fully local extraction workflow."""

from __future__ import annotations

import sys

from config import INPUT_DIR, OUTPUT_FILE, TEMP_DIR
from excel_writer import deduplicate, validate_workbook, write_workbook
from models import ProcessingIssue, WorkbookRecord
from ollama_extractor import OllamaExtractor
from pdf_processor import PdfProcessingError, cleanup_generated_images, process_pdf


def main() -> int:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_generated_images()

    pdf_files = sorted(
        (path for path in INPUT_DIR.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: path.name.casefold(),
    )
    if not pdf_files:
        print(f"No PDF files found in: {INPUT_DIR}")
        return 1

    extractor = OllamaExtractor()

    all_records: list[WorkbookRecord] = []
    all_issues: list[ProcessingIssue] = []
    try:
        for index, pdf_path in enumerate(pdf_files, start=1):
            print(f"[{index}/{len(pdf_files)}] Processing {pdf_path.name}")
            try:
                records, issues = process_pdf(pdf_path, extractor)
                all_records.extend(records)
                all_issues.extend(issues)
            except PdfProcessingError as exc:
                all_issues.append(
                    ProcessingIssue(source_pdf=pdf_path.name, issue=str(exc))
                )
                print(f"    Warning: {exc}; continuing.")

        all_records = deduplicate(all_records)
        print("Creating Excel workbook...")
        write_workbook(all_records, all_issues, OUTPUT_FILE)
        validate_workbook(OUTPUT_FILE, all_records)

        leftovers = list(TEMP_DIR.glob("page_*.png"))
        if leftovers:
            raise RuntimeError("Temporary page images could not be fully removed")
    except Exception as exc:
        print(f"Error: processing did not complete ({type(exc).__name__}).")
        return 1
    finally:
        cleanup_generated_images()

    locations = {
        " ".join((record.location or "UNRESOLVED").split()).casefold()
        for record in all_records
    }
    print("Completed.")
    print(f"Locations extracted: {len(locations)}")
    print(f"Users extracted: {len(all_records)}")
    print(f"Pages/PDFs requiring review: {len(all_issues)}")
    print(f"Output: {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
