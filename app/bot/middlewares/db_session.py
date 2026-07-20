from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.database.session import async_session_factory
from app.repositories.aircraft_repository import AircraftRepository
from app.repositories.flight_repository import FlightRepository
from app.services.aircraft_service import AircraftService
from app.services.flight_service import FlightService


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
                    data["user"] = await aircraft_service.get_or_create_user(tg_user.id)

                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
