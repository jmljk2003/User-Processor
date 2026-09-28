"""Central configuration for the local user-listing extractor."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _get_int(name: str, default: int, minimum: int = 0) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b").strip()
PDF_RENDER_SCALE = _get_float("PDF_RENDER_SCALE", 4.0)
OLLAMA_TIMEOUT = _get_int("OLLAMA_TIMEOUT", 600, minimum=1)
OLLAMA_NUM_CTX = _get_int("OLLAMA_NUM_CTX", 8192, minimum=4096)
MAX_EXTRACTION_RETRIES = _get_int("MAX_EXTRACTION_RETRIES", 2)
REVIEW_CONFIDENCE_THRESHOLD = _get_float("REVIEW_CONFIDENCE_THRESHOLD", 0.80)
IMAGE_CONTRAST = _get_float("IMAGE_CONTRAST", 1.08)
IMAGE_SHARPNESS = _get_float("IMAGE_SHARPNESS", 1.15)

INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_FILE = OUTPUT_DIR / "User_Access_Listing.xlsx"


if not OLLAMA_MODEL:
    raise ValueError("OLLAMA_MODEL cannot be empty")
if REVIEW_CONFIDENCE_THRESHOLD > 1:
    raise ValueError("REVIEW_CONFIDENCE_THRESHOLD cannot be greater than 1")

_ollama_url = urlparse(OLLAMA_HOST)
if _ollama_url.scheme not in {"http", "https"} or _ollama_url.hostname not in {
    "localhost",
    "127.0.0.1",
    "::1",
}:
    raise ValueError(
        "OLLAMA_HOST must use a loopback address (localhost, 127.0.0.1, or ::1)"
    )
