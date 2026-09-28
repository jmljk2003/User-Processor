"""Fast, local extraction for PDFs that contain a usable text layer."""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf as fitz

from models import PageExtraction, UserRecord


@dataclass(frozen=True)
class _ColumnLayout:
    header_y: float
    user_x: float
    role_x: float
    email_x: float
    mfa_x: float
    action_x: float


def _word_text(word: tuple) -> str:
    return str(word[4]).strip()


def _detect_columns(words: list[tuple]) -> _ColumnLayout | None:
    email_headers = [
        word
        for word in words
        if _word_text(word).casefold() == "email" and float(word[0]) > 100
    ]
    for email_header in sorted(email_headers, key=lambda word: float(word[1])):
        header_y = float(email_header[1])
        nearby = [word for word in words if abs(float(word[1]) - header_y) <= 3.5]
        user_headers = sorted(
            (
                word
                for word in nearby
                if _word_text(word).casefold() == "user"
                and float(word[0]) < float(email_header[0])
            ),
            key=lambda word: float(word[0]),
        )
        mfa_headers = [
            word
            for word in nearby
            if _word_text(word).casefold() in {"multi-factor", "authentication"}
            and float(word[0]) > float(email_header[0])
        ]
        action_headers = [
            word
            for word in nearby
            if _word_text(word).casefold() == "action"
            and float(word[0]) > float(email_header[0])
        ]
        if len(user_headers) < 2 or not mfa_headers or not action_headers:
            continue

        layout = _ColumnLayout(
            header_y=header_y,
            user_x=float(user_headers[0][0]),
            role_x=float(user_headers[-1][0]),
            email_x=float(email_header[0]),
            mfa_x=min(float(word[0]) for word in mfa_headers),
            action_x=min(float(word[0]) for word in action_headers),
        )
        if layout.user_x < layout.role_x < layout.email_x < layout.mfa_x < layout.action_x:
            return layout
    return None


def _cluster_rows(words: list[tuple], tolerance: float = 2.0) -> list[list[tuple]]:
    clusters: list[list[tuple]] = []
    centers: list[float] = []
    for word in sorted(words, key=lambda item: (float(item[1]), float(item[0]))):
        y = float(word[1])
        if clusters and abs(y - centers[-1]) <= tolerance:
            clusters[-1].append(word)
            centers[-1] = sum(float(item[1]) for item in clusters[-1]) / len(clusters[-1])
        else:
            clusters.append([word])
            centers.append(y)
    return clusters


def _join_column(row: list[tuple], start_x: float, end_x: float) -> str:
    parts = [
        _word_text(word)
        for word in sorted(row, key=lambda item: float(item[0]))
        if start_x - 0.5 <= float(word[0]) < end_x - 0.5 and _word_text(word)
    ]
    return " ".join(parts).strip()


def _extract_location(words: list[tuple], header_y: float, page_width: float) -> tuple[str, str]:
    candidates = [
        word
        for word in words
        if float(word[0]) < page_width * 0.40 and float(word[1]) < header_y - 20
    ]
    lines = _cluster_rows(candidates, tolerance=1.2)
    lines = [line for line in lines if any(_word_text(word) for word in line)]
    if not lines:
        return "", ""

    location_line = min(lines, key=lambda line: min(float(word[1]) for word in line))
    location_y = sum(float(word[1]) for word in location_line) / len(location_line)
    location = " ".join(
        _word_text(word)
        for word in sorted(location_line, key=lambda item: float(item[0]))
        if _word_text(word)
    ).strip()

    location_id = ""
    later_lines = sorted(
        (
            line
            for line in lines
            if min(float(word[1]) for word in line) > location_y + 1
            and min(float(word[1]) for word in line) < location_y + 14
        ),
        key=lambda line: min(float(word[1]) for word in line),
    )
    for line in later_lines:
        text = "".join(_word_text(word) for word in sorted(line, key=lambda item: float(item[0])))
        if text.isdigit():
            location_id = text
            break
    return location, location_id


def extract_from_text_layer(page: fitz.Page) -> PageExtraction | None:
    """Return a validated extraction, or None when vision fallback is required."""
    words = list(page.get_text("words", sort=False))
    if not words:
        return None

    layout = _detect_columns(words)
    if layout is None:
        return None

    data_words = [
        word
        for word in words
        if float(word[1]) >= layout.header_y + 8
        and float(word[1]) < page.rect.height - 10
        and layout.user_x - 0.5 <= float(word[0]) < layout.action_x - 0.5
    ]
    rows = _cluster_rows(data_words)
    users: list[UserRecord] = []
    for row in rows:
        user_name = _join_column(row, layout.user_x, layout.role_x)
        role = _join_column(row, layout.role_x, layout.email_x)
        email = _join_column(row, layout.email_x, layout.mfa_x)
        mfa = _join_column(row, layout.mfa_x, layout.action_x)
        if not any((user_name, role, email, mfa)):
            continue
        users.append(
            UserRecord(
                user_name=user_name,
                user_role_name=role,
                email=email,
                mfa=mfa,
                confidence=0.99,
            )
        )

    # Requiring actual rows prevents an unrelated page with similar labels from
    # suppressing the vision fallback.
    if not users:
        return None

    location, location_id = _extract_location(words, layout.header_y, page.rect.width)
    return PageExtraction(
        location=location,
        location_id=location_id,
        location_confidence=0.99 if location else None,
        users=users,
    )
