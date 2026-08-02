"""Shared parsing/formatting helpers for bot handlers. No aiogram Router lives here."""
from __future__ import annotations

import datetime
import re
from decimal import Decimal, InvalidOperation

from app.bot.texts.i18n import t
from app.database.models import User
from app.domain.units import compact_decimal, to_decimal
from app.services.aircraft_service import AircraftService, build_domain_profile


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
    # Keep wizard and history values canonical so ``40.0000`` cannot leak into UI text.
    return to_decimal(compact_decimal(value))


def parse_optional_decimal(text: str) -> Decimal | None:
    if text.strip().lower() in {"skip", "-"}:
        return None
    return parse_decimal(text)


def parse_optional_text(text: str) -> str | None:
    text = text.strip()
    if not text or text.lower() in {"skip", "-"}:
        return None
    return text


def parse_optional_date(text: str) -> datetime.date | None:
    text = text.strip()
    if not text or text.lower() in {"skip", "-"}:
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


def lang(user: User) -> str:
    return user.language or "en"


async def load_profile_and_aircraft(
    user_id: int, aircraft_id: int, aircraft_service: AircraftService
):
    """Shared by every calculation flow: resolve an aircraft's active revision into the
    domain profile the calculator needs, or (None, None) if it isn't set up yet."""
    aircraft = await aircraft_service.get_aircraft(user_id, aircraft_id)
    if aircraft is None or aircraft.active_revision_id is None:
        return None, None
    revision = await aircraft_service.get_revision_for_user(
        user_id, aircraft.active_revision_id
    )
    if revision is None:
        return None, None
    return aircraft, build_domain_profile(revision, aircraft)


def recommendation_text(recommendations, lang_code: str) -> str:
    """Render a load/fuel adjustment recommendation list the same way in every calculation
    flow -- Quick and Advanced both hit this once their result comes back OUT_OF_LIMITS."""
    if not recommendations:
        return t("no_recommendations", lang_code)
    lines = [t("recommendations_header", lang_code)]
    for index, recommendation in enumerate(recommendations, start=1):
        lines.append(f"{index}. {recommendation.describe()}")
        # QuickRecommendation has no `note` field at all (Quick never sets one); Advanced's
        # Recommendation still carries one for SHIFT_FUEL -- getattr covers both shapes.
        note = getattr(recommendation, "note", None)
        if note:
            lines.append(f"   {note}")
    return "\n".join(lines)


def short_tank_label(name: str) -> str:
    """Return a concise label derived from a configured tank name.

    Tank roles remain aircraft-profile data; this only removes redundant English words such
    as ``Fuel`` and ``Tanks`` for compact pilot-facing lists. Non-English and custom names are
    preserved when no generic English words are present.
    """
    cleaned_name = name.strip()
    words = cleaned_name.split()
    generic_words = {"fuel", "tank", "tanks"}
    concise_words = [
        word
        for word in words
        if re.sub(r"[^a-z]", "", word.lower()) not in generic_words
    ]
    concise = " ".join(concise_words).strip(" -–—,;/")
    return concise or cleaned_name
