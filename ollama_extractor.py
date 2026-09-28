"""Local-only Ollama vision client with strict validation and retries."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import requests
from pydantic import ValidationError

from config import (
    MAX_EXTRACTION_RETRIES,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_TIMEOUT,
)
from models import PageExtraction


EXTRACTION_PROMPT = """You are reading a screenshot of a User Management page.

Extract ONLY information visibly present in the screenshot.
The location/property name normally appears in the upper-left corner. A numeric
value immediately underneath it may be the property/location ID.

Extract every visible user row from the User Management table. Expected columns:
- User Name
- User Role Name
- Email
- Multi-Factor Authentication

Ignore Action, buttons, icons, navigation menus, page headings, search bars, and
unrelated UI elements.

VERY IMPORTANT:
- Never invent missing values or infer usernames, roles, emails, or MFA status.
- If text cannot be read confidently, return an empty string.
- Preserve visible text as closely as possible.
- Do not combine different user rows.
- Confidence values must be numbers from 0 to 1 and should reflect legibility.
- Use this structure:
  {"location":"", "location_id":"", "location_confidence":0.0,
   "users":[{"user_name":"", "user_role_name":"", "email":"",
   "mfa":"", "confidence":0.0}]}
- Return valid JSON only, matching the supplied schema exactly.
"""


class OllamaUnavailableError(RuntimeError):
    pass


class OllamaModelMissingError(RuntimeError):
    pass


class PageExtractionError(RuntimeError):
    pass


class OllamaExtractor:
    def __init__(self) -> None:
        self.session = requests.Session()
        # Never allow environment proxy settings to relay page images elsewhere.
        self.session.trust_env = False
        self._preflight_complete = False

    def preflight(self) -> None:
        try:
            response = self.session.get(
                f"{OLLAMA_HOST}/api/tags",
                timeout=min(OLLAMA_TIMEOUT, 15),
                allow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, AttributeError, ValueError) as exc:
            raise OllamaUnavailableError(
                f"Ollama is not reachable at {OLLAMA_HOST}. Start Ollama and try again."
            ) from exc

        installed = {
            str(model.get("name") or model.get("model") or "")
            for model in payload.get("models", [])
            if isinstance(model, dict)
        }
        if OLLAMA_MODEL not in installed:
            raise OllamaModelMissingError(
                f"Configured Ollama model '{OLLAMA_MODEL}' is not installed. "
                "Set OLLAMA_MODEL in .env to an installed vision-capable model."
            )
        self._preflight_complete = True

    def extract_page(self, image_path: Path) -> PageExtraction:
        if not self._preflight_complete:
            self.preflight()
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        request_body = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "format": PageExtraction.model_json_schema(),
            "messages": [
                {
                    "role": "user",
                    "content": EXTRACTION_PROMPT,
                    "images": [image_b64],
                }
            ],
            "options": {"temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
        }

        last_error: Exception | None = None
        for _attempt in range(MAX_EXTRACTION_RETRIES + 1):
            try:
                response = self.session.post(
                    f"{OLLAMA_HOST}/api/chat",
                    json=request_body,
                    timeout=OLLAMA_TIMEOUT,
                    allow_redirects=False,
                )
                response.raise_for_status()
                content = response.json()["message"]["content"]
                if isinstance(content, dict):
                    parsed = content
                else:
                    parsed = json.loads(content)
                return PageExtraction.model_validate(parsed)
            except requests.HTTPError as exc:
                # Older Ollama releases accept "json" but not a JSON schema.
                if (
                    exc.response is not None
                    and exc.response.status_code == 400
                    and isinstance(request_body["format"], dict)
                ):
                    request_body["format"] = "json"
                last_error = exc
            except requests.Timeout as exc:
                # Ollama may continue server-side generation after a client timeout.
                # Retrying immediately can queue duplicate, expensive vision jobs.
                raise PageExtractionError(
                    f"Ollama did not finish within {OLLAMA_TIMEOUT} seconds"
                ) from exc
            except (
                requests.RequestException,
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
                ValidationError,
            ) as exc:
                last_error = exc

        # Never include the response body: it may contain extracted PII.
        raise PageExtractionError(
            f"Ollama returned no valid extraction after {MAX_EXTRACTION_RETRIES + 1} attempts"
        ) from last_error
