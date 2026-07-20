from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import aircraft_list_keyboard, main_menu_keyboard
from app.bot.texts.i18n import t
from app.database.models import Aircraft, User
from app.services.aircraft_service import AircraftService

router = Router(name="menu")


def _lang(user: User) -> str:
    return user.language or "en"


@router.message(Command("start"))
async def cmd_start(message: Message, user: User) -> None:
    lang = _lang(user)
    await message.answer(t("welcome", lang), parse_mode="Markdown")
    await message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))


@router.message(Command("help"))
@router.message(F.text.in_({t("menu_help", "en"), t("menu_help", "ru")}))
async def cmd_help(message: Message, user: User) -> None:
    await message.answer(t("help_text", _lang(user)))


@router.message(Command("cancel"))
@router.message(F.text.in_({t("menu_cancel", "en"), t("menu_cancel", "ru")}))
async def cmd_cancel(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await message.answer(t("cancelled", lang), reply_markup=main_menu_keyboard(lang))


def _aircraft_banner(aircraft: Aircraft, lang: str) -> str:
    revision = aircraft.active_revision
    rev_text = f"rev. {revision.revision_number}" if revision else "no revision"
    nickname = f" \"{aircraft.nickname}\"" if aircraft.nickname else ""
    return f"{aircraft.tail_number}{nickname} -- {aircraft.model} ({rev_text})"


@router.message(F.text.in_({t("menu_my_aircraft", "en"), t("menu_my_aircraft", "ru")}))
async def my_aircraft(message: Message, user: User, aircraft_service: AircraftService) -> None:
    lang = _lang(user)
    aircraft_list = await aircraft_service.list_aircraft(user.id)
    if not aircraft_list:
        await message.answer(t("no_aircraft_yet", lang))
        return
    lines = [t("unverified_banner", lang), ""]
    for a in aircraft_list:
        marker = " ⭐" if user.selected_aircraft_id == a.id else ""
        lines.append(f"- {_aircraft_banner(a, lang)}{marker}")
    await message.answer("\n".join(lines))


@router.message(F.text.in_({t("menu_select_aircraft", "en"), t("menu_select_aircraft", "ru")}))
async def select_aircraft_prompt(message: Message, user: User, aircraft_service: AircraftService) -> None:
    lang = _lang(user)
    aircraft_list = await aircraft_service.list_aircraft(user.id)
    if not aircraft_list:
        await message.answer(t("no_aircraft_yet", lang))
        return
    await message.answer(
        t("select_aircraft_prompt", lang), reply_markup=aircraft_list_keyboard(aircraft_list, "select")
    )


@router.callback_query(F.data.startswith("select:"))
async def select_aircraft_chosen(
    callback: CallbackQuery, user: User, aircraft_service: AircraftService
) -> None:
    lang = _lang(user)
    aircraft_id = int(callback.data.split(":")[1])
    aircraft = await aircraft_service.get_aircraft(user.id, aircraft_id)
    if aircraft is None:
        await callback.answer()
        return
    await aircraft_service.select_aircraft(user, aircraft.id)
    await callback.message.edit_text(f"{_aircraft_banner(aircraft, lang)}\n\n{t('aircraft_selected', lang)}")
    await callback.answer()


@router.message(F.text.in_({t("menu_archive_aircraft", "en"), t("menu_archive_aircraft", "ru")}))
async def archive_aircraft_prompt(message: Message, user: User, aircraft_service: AircraftService) -> None:
    lang = _lang(user)
    aircraft_list = await aircraft_service.list_aircraft(user.id)
    if not aircraft_list:
        await message.answer(t("no_aircraft_yet", lang))
        return
    await message.answer(
        t("select_aircraft_prompt", lang), reply_markup=aircraft_list_keyboard(aircraft_list, "archive")
    )


@router.callback_query(F.data.startswith("archive:"))
async def archive_aircraft_chosen(
    callback: CallbackQuery, user: User, aircraft_service: AircraftService
) -> None:
    lang = _lang(user)
    aircraft_id = int(callback.data.split(":")[1])
    aircraft = await aircraft_service.get_aircraft(user.id, aircraft_id)
    if aircraft is None:
        await callback.answer()
        return
    await aircraft_service.archive_aircraft(aircraft)
    if user.selected_aircraft_id == aircraft.id:
        await aircraft_service.select_aircraft(user, None)
    await callback.message.edit_text(f"{aircraft.tail_number} archived.")
    await callback.answer()
