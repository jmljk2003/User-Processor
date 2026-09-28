"""Validated data models used by extraction and workbook generation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


class UserRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_name: str = ""
    user_role_name: str = ""
    email: str = ""
    mfa: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("user_name", "user_role_name", "email", mode="before")
    @classmethod
    def clean_strings(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("mfa", mode="before")
    @classmethod
    def normalize_mfa(cls, value: Any) -> str:
        text = _clean_text(value)
        normalized = text.lower()
        if "disabled" in normalized:
            return "Disabled"
        if "enabled" in normalized:
            return "Enabled"
        return ""


class PageExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    location: str = ""
    location_id: str = ""
    location_confidence: float | None = Field(default=None, ge=0, le=1)
    users: list[UserRecord] = Field(default_factory=list)

    @field_validator("location", "location_id", mode="before")
    @classmethod
    def clean_strings(cls, value: Any) -> str:
        return _clean_text(value)


class WorkbookRecord(BaseModel):
    location: str
    user_name: str
    user_role_name: str
    email: str
    mfa: str
    review_required: str
    source_pdf: str
    page: int = Field(ge=1)


class ProcessingIssue(BaseModel):
    source_pdf: str
    page: int | None = None
    issue: str
