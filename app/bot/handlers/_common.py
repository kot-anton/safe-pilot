"""Shared parsing/formatting helpers for bot handlers. No aiogram Router lives here."""
from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation

from app.domain.units import to_decimal


class InputParseError(Exception):
    pass


def parse_decimal(text: str, *, allow_negative: bool = False) -> Decimal:
    text = text.strip().replace(",", ".")
    try:
        value = to_decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise InputParseError("not a valid number") from exc
    if not value.is_finite():
        raise InputParseError("number must be finite")
    if not allow_negative and value < 0:
        raise InputParseError("value cannot be negative")
    return value


def parse_optional_decimal(text: str) -> Decimal | None:
    if text.strip().lower() in {"skip", "-", "пропустить"}:
        return None
    return parse_decimal(text)


def parse_optional_text(text: str) -> str | None:
    text = text.strip()
    if not text or text.lower() in {"skip", "-", "пропустить"}:
        return None
    return text


def parse_optional_date(text: str) -> datetime.date | None:
    text = text.strip()
    if not text or text.lower() in {"skip", "-", "пропустить"}:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError as exc:
        raise InputParseError("expected YYYY-MM-DD") from exc


def fmt(value: Decimal | None, unit: str = "") -> str:
    """Rounds to one decimal place and drops it when it's just a trailing zero, so a stored
    Decimal("53.0000") reads as "53 gal" rather than "53.0000 gal", but "53.5" is preserved."""
    if value is None:
        return "not set"
    quantized = value.quantize(Decimal("0.1"))
    text = f"{quantized}"
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text}{unit}"
