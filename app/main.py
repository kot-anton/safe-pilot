import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import aircraft_update, aircraft_wizard, flight_calculation, menu, quick_calculate
from app.bot.middlewares.db_session import DbSessionMiddleware
from app.config import settings

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("safe_pilot")


async def main() -> None:
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=None))
    dispatcher = Dispatcher(storage=MemoryStorage())

    db_middleware = DbSessionMiddleware()
    dispatcher.message.middleware(db_middleware)
    dispatcher.callback_query.middleware(db_middleware)

    dispatcher.include_router(menu.router)
    dispatcher.include_router(quick_calculate.router)
    dispatcher.include_router(aircraft_wizard.router)
    dispatcher.include_router(aircraft_update.router)
    dispatcher.include_router(flight_calculation.router)

    logger.info("Starting Safe Pilot bot (long polling)")
    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
