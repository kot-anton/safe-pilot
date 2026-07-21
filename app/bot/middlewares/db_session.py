from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.config import settings
from app.database.session import async_session_factory
from app.repositories.aircraft_repository import AircraftRepository
from app.repositories.flight_repository import FlightRepository
from app.services.aircraft_service import AircraftService
from app.services.flight_service import FlightService

SUPPORTED_LANGUAGES = {"en", "ru"}


def preferred_language(telegram_language_code: str | None, fallback: str) -> str:
    """Choose a supported UI language for a new user without changing returning users."""
    telegram_language = (telegram_language_code or "").split("-", 1)[0].lower()
    if telegram_language in SUPPORTED_LANGUAGES:
        return telegram_language
    normalized_fallback = fallback.lower()
    return normalized_fallback if normalized_fallback in SUPPORTED_LANGUAGES else "en"


class DbSessionMiddleware(BaseMiddleware):
    """Opens one DB session/transaction per update and injects ready-to-use services.

    Commits on success, rolls back on any handler exception -- no partial writes leak out.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session_factory() as session:
            try:
                data["session"] = session
                aircraft_service = AircraftService(AircraftRepository(session))
                data["aircraft_service"] = aircraft_service
                data["flight_service"] = FlightService(FlightRepository(session))

                tg_user = data.get("event_from_user")
                if tg_user is not None:
                    data["user"] = await aircraft_service.get_or_create_user(
                        tg_user.id,
                        preferred_language(tg_user.language_code, settings.default_language),
                    )

                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
