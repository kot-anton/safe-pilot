from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import (
    aircraft_card_keyboard,
    aircraft_list_keyboard,
    aircraft_submenu_keyboard,
    main_menu_keyboard,
    more_submenu_keyboard,
)
from app.bot.texts.i18n import t
from app.database.models import Aircraft, User
from app.services.aircraft_service import AircraftService
from app.services.flight_service import FlightService

router = Router(name="menu")


def _lang(user: User) -> str:
    return user.language or "en"


@router.message(Command("start"))
async def cmd_start(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
) -> None:
    await state.clear()
    lang = _lang(user)
    await message.answer(t("welcome", lang), parse_mode="Markdown")

    active_aircraft = None
    if user.selected_aircraft_id:
        active_aircraft = await aircraft_service.get_aircraft(user.id, user.selected_aircraft_id)

    if active_aircraft is not None:
        await message.answer(
            _aircraft_card(active_aircraft), reply_markup=aircraft_card_keyboard(lang)
        )
    await message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))


@router.message(Command("aircraft"))
@router.message(F.text.in_({t("menu_aircraft_submenu", "en"), t("menu_aircraft_submenu", "ru")}))
async def aircraft_submenu(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await message.answer(t("aircraft_menu", lang), reply_markup=aircraft_submenu_keyboard(lang))


@router.message(F.text.in_({t("menu_more_submenu", "en"), t("menu_more_submenu", "ru")}))
async def more_submenu(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await message.answer(t("more_menu", lang), reply_markup=more_submenu_keyboard(lang))


@router.message(Command("menu"))
@router.message(F.text.in_({t("menu_back", "en"), t("menu_back", "ru")}))
async def back_to_main_menu(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))


def _aircraft_card(aircraft: Aircraft) -> str:
    nickname = f"\n{aircraft.nickname}" if aircraft.nickname else ""
    return f"{aircraft.tail_number}{nickname}\n{aircraft.model}"


@router.callback_query(F.data == "card:calculate")
async def card_calculate(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
) -> None:
    from app.bot.handlers.quick_calculate import show_calculation_options

    await callback.answer()
    await show_calculation_options(callback.message, state, user)


@router.callback_query(F.data == "card:change_aircraft")
async def card_change_aircraft(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
) -> None:
    await state.clear()
    await callback.answer()
    await _send_select_aircraft_prompt(callback.message, user, aircraft_service)


@router.message(Command("help"))
@router.message(F.text.in_({t("menu_help", "en"), t("menu_help", "ru")}))
async def cmd_help(message: Message, user: User) -> None:
    await message.answer(t("help_text", _lang(user)))


@router.message(Command("history"))
async def cmd_history(
    message: Message,
    state: FSMContext,
    user: User,
    flight_service: FlightService,
    aircraft_service: AircraftService,
) -> None:
    # This router is registered first, so /history cannot be mistaken for numeric wizard input.
    from app.bot.handlers.flight_calculation import calculation_history

    await calculation_history(message, state, user, flight_service, aircraft_service)


@router.message(Command("cancel"))
@router.message(F.text.in_({t("menu_cancel", "en"), t("menu_cancel", "ru")}))
async def cmd_cancel(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await message.answer(t("cancelled", lang), reply_markup=main_menu_keyboard(lang))


def _aircraft_banner(aircraft: Aircraft) -> str:
    nickname = f" \"{aircraft.nickname}\"" if aircraft.nickname else ""
    return f"{aircraft.tail_number}{nickname} -- {aircraft.model}"


@router.message(F.text.in_({t("menu_my_aircraft", "en"), t("menu_my_aircraft", "ru")}))
async def my_aircraft(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
) -> None:
    await state.clear()
    lang = _lang(user)
    aircraft_list = await aircraft_service.list_aircraft(user.id)
    if not aircraft_list:
        await message.answer(t("no_aircraft_yet", lang))
        return
    lines = [t("my_aircraft_header", lang), ""]
    for a in aircraft_list:
        marker = " ⭐" if user.selected_aircraft_id == a.id else ""
        lines.append(f"- {_aircraft_banner(a)}{marker}")
    await message.answer("\n".join(lines))


@router.message(F.text.in_({t("menu_select_aircraft", "en"), t("menu_select_aircraft", "ru")}))
async def select_aircraft_prompt(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
) -> None:
    await state.clear()
    await _send_select_aircraft_prompt(message, user, aircraft_service)


async def _send_select_aircraft_prompt(
    message: Message, user: User, aircraft_service: AircraftService
) -> None:
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
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
) -> None:
    await state.clear()
    lang = _lang(user)
    aircraft_id = int(callback.data.split(":")[1])
    aircraft = await aircraft_service.get_aircraft(user.id, aircraft_id)
    if aircraft is None:
        await callback.answer(t("aircraft_not_found", lang), show_alert=True)
        return
    await aircraft_service.select_aircraft(user, aircraft.id)
    await callback.message.edit_text(f"{_aircraft_banner(aircraft)}\n\n{t('aircraft_selected', lang)}")
    await callback.answer()
    await callback.message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))


@router.message(F.text.in_({t("menu_archive_aircraft", "en"), t("menu_archive_aircraft", "ru")}))
async def archive_aircraft_prompt(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
) -> None:
    await state.clear()
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
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
) -> None:
    await state.clear()
    lang = _lang(user)
    aircraft_id = int(callback.data.split(":")[1])
    aircraft = await aircraft_service.get_aircraft(user.id, aircraft_id)
    if aircraft is None:
        await callback.answer(t("aircraft_not_found", lang), show_alert=True)
        return
    await aircraft_service.archive_aircraft(aircraft)
    if user.selected_aircraft_id == aircraft.id:
        await aircraft_service.select_aircraft(user, None)
    await callback.message.edit_text(t("aircraft_archived", lang, aircraft=aircraft.tail_number))
    await callback.answer()
    await callback.message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))
