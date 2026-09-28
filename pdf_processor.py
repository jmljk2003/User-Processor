"""Sequential PDF rendering, image preprocessing, and record assembly."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pymupdf as fitz
from PIL import Image, ImageEnhance

from config import (
    IMAGE_CONTRAST,
    IMAGE_SHARPNESS,
    PDF_RENDER_SCALE,
    REVIEW_CONFIDENCE_THRESHOLD,
    TEMP_DIR,
)
from local_text_extractor import extract_from_text_layer
from models import ProcessingIssue, WorkbookRecord
from ollama_extractor import OllamaExtractor


class PdfProcessingError(RuntimeError):
    pass


def cleanup_generated_images() -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    for image_path in TEMP_DIR.glob("page_*.png"):
        try:
            image_path.unlink()
        except OSError:
            # The final validation will report any file that could not be removed.
            pass


def _render_page(page: fitz.Page, destination: Path) -> None:
    matrix = fitz.Matrix(PDF_RENDER_SCALE, PDF_RENDER_SCALE)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csRGB)
    pixmap.save(destination)


def _preprocess_image(image_path: Path) -> None:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    # Save only after the source handle is closed (required when overwriting on Windows).
    image = ImageEnhance.Contrast(image).enhance(IMAGE_CONTRAST)
    image = ImageEnhance.Sharpness(image).enhance(IMAGE_SHARPNESS)
    image.save(image_path, format="PNG", optimize=False)


def _needs_review(
    *,
    username: str,
    role: str,
    user_confidence: float | None,
    location_confidence: float | None,
    inherited_location: bool,
    unresolved_location: bool,
) -> bool:
    confidences = [c for c in (user_confidence, location_confidence) if c is not None]
    low_confidence = any(c < REVIEW_CONFIDENCE_THRESHOLD for c in confidences)
    unclear_role = role.strip().casefold() in {
        "?",
        "unclear",
        "unknown",
        "illegible",
        "unreadable",
    }
    return (
        low_confidence
        or not username
        or not role
        or unclear_role
        or inherited_location
        or unresolved_location
    )


def process_pdf(
    pdf_path: Path, extractor: OllamaExtractor
) -> tuple[list[WorkbookRecord], list[ProcessingIssue]]:
    records: list[WorkbookRecord] = []
    issues: list[ProcessingIssue] = []
    previous_location = ""
    previous_location_confidence: float | None = None

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        raise PdfProcessingError("PDF could not be opened (it may be invalid or corrupted)") from exc

    try:
        if document.needs_pass:
            raise PdfProcessingError("PDF is password-protected")

        total_pages = document.page_count
        if total_pages == 0:
            raise PdfProcessingError("PDF contains no pages")

        for page_index in range(total_pages):
            page_number = page_index + 1
            print(f"    Page {page_number}/{total_pages}")
            temp_image = TEMP_DIR / f"page_{uuid4().hex}.png"
            try:
                page = document.load_page(page_index)
                extraction = extract_from_text_layer(page)
                if extraction is not None:
                    print("        Local text layer used.")
                else:
                    _render_page(page, temp_image)
                    _preprocess_image(temp_image)
                    extraction = extractor.extract_page(temp_image)
            except Exception:
                # Do not inherit a location across a page whose contents are unknown.
                previous_location = ""
                previous_location_confidence = None
                issues.append(
                    ProcessingIssue(
                        source_pdf=pdf_path.name,
                        page=page_number,
                        issue="Page extraction failed",
                    )
                )
                print("        Warning: page extraction failed; continuing.")
                continue
            finally:
                try:
                    temp_image.unlink(missing_ok=True)
                except OSError:
                    pass

            visible_location = extraction.location
            inherited_location = False
            if visible_location:
                location = visible_location
                previous_location = visible_location
                previous_location_confidence = extraction.location_confidence
                location_confidence = extraction.location_confidence
            elif extraction.users and previous_location:
                location = previous_location
                location_confidence = previous_location_confidence
                inherited_location = True
            else:
                location = "UNRESOLVED"
                location_confidence = extraction.location_confidence

            if not extraction.users:
                issues.append(
                    ProcessingIssue(
                        source_pdf=pdf_path.name,
                        page=page_number,
                        issue="No users detected",
                    )
                )
                if not visible_location:
                    previous_location = ""
                    previous_location_confidence = None
                continue

            unresolved = location == "UNRESOLVED"
            for user in extraction.users:
                review = _needs_review(
                    username=user.user_name,
                    role=user.user_role_name,
                    user_confidence=user.confidence,
                    location_confidence=location_confidence,
                    inherited_location=inherited_location,
                    unresolved_location=unresolved,
                )
                records.append(
                    WorkbookRecord(
                        location=location,
                        user_name=user.user_name,
                        user_role_name=user.user_role_name,
                        email=user.email,
                        mfa=user.mfa,
                        review_required="YES" if review else "NO",
                        source_pdf=pdf_path.name,
                        page=page_number,
                    )
                )
    finally:
        document.close()

    return records, issues
