"""Telegram command-list and menu-button configuration.

Reply keyboards are useful once a conversation is open, but Telegram's persistent ``Menu``
button is driven by registered bot commands.  Configure both surfaces so a user can always
recover the main menu, including after a deployment or an interrupted FSM conversation.
"""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    MenuButtonCommands,
)

from app.bot.texts.i18n import t


COMMAND_TEXT_KEYS: tuple[tuple[str, str], ...] = (
    ("start", "command_start"),
    ("menu", "command_menu"),
    ("calculate", "command_calculate"),
    ("aircraft", "command_aircraft"),
    ("history", "command_history"),
    ("help", "command_help"),
    ("cancel", "command_cancel"),
)


def bot_commands(lang: str) -> list[BotCommand]:
    return [
        BotCommand(command=command, description=t(text_key, lang))
        for command, text_key in COMMAND_TEXT_KEYS
    ]


async def configure_bot_ui(bot: Bot) -> None:
    """Register default/translated commands and force Telegram's command menu button on."""
    scope = BotCommandScopeAllPrivateChats()
    await bot.set_my_commands(bot_commands("en"), scope=scope)
    await bot.set_my_commands(bot_commands("ru"), scope=scope, language_code="ru")
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
