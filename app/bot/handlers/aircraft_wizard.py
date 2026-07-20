"""Aircraft creation wizard. Pure Telegram presentation glue -- all math happens in app.domain
and app.services; this file only collects and validates user input step by step."""
from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers._common import (
    InputParseError,
    fmt,
    parse_decimal,
    parse_optional_date,
    parse_optional_decimal,
    parse_optional_text,
)
from app.bot.keyboards.common import (
    STATION_TYPE_DEFAULT_NAMES,
    add_another_station_keyboard,
    arm_fixed_adjustable_keyboard,
    cancel_only_keyboard,
    cg_or_moment_keyboard,
    confirm_keyboard,
    keep_cancel_keyboard,
    main_menu_keyboard,
    skip_cancel_keyboard,
    station_type_keyboard,
    yes_no_keyboard,
)
from app.bot.states.aircraft_wizard import AircraftWizard
from app.bot.texts.i18n import t
from app.database.models import StationTypeEnum, User
from app.domain.envelope import CGEnvelope, EnvelopeRow
from app.domain.exceptions import InvalidEnvelopeError
from app.domain.models import StationType
from app.services.aircraft_service import (
    AircraftRevisionDraft,
    EnvelopeRowDraft,
    StationDraft,
    useful_load_warning,
)
from app.services.aircraft_service import AircraftService

router = Router(name="aircraft_wizard")


def _lang(user: User) -> str:
    return user.language or "en"


@router.message(F.text.in_({t("menu_add_aircraft", "en"), t("menu_add_aircraft", "ru")}))
async def start_wizard(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    await state.update_data(stations=[], envelope_rows=[])
    await state.set_state(AircraftWizard.tail_number)
    await message.answer(t("ask_tail_number", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


@router.callback_query(F.data == "wizard:cancel")
async def wizard_cancel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await callback.message.edit_text(t("cancelled", lang))
    await callback.message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))
    await callback.answer()


@router.message(AircraftWizard.tail_number)
async def got_tail_number(message: Message, state: FSMContext, user: User) -> None:
    tail_number = message.text.strip().upper()
    if not tail_number:
        await message.answer(t("error_generic", _lang(user), detail="tail number required"))
        return
    await state.update_data(tail_number=tail_number)
    await state.set_state(AircraftWizard.nickname)
    await message.answer(t("ask_nickname", _lang(user)), reply_markup=skip_cancel_keyboard(_lang(user)))


@router.message(AircraftWizard.nickname)
async def got_nickname(message: Message, state: FSMContext, user: User) -> None:
    await state.update_data(nickname=parse_optional_text(message.text))
    await state.set_state(AircraftWizard.manufacturer)
    await message.answer(t("ask_manufacturer", _lang(user)), reply_markup=skip_cancel_keyboard(_lang(user)))


@router.callback_query(AircraftWizard.nickname, F.data == "wizard:skip")
async def skip_nickname(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(nickname=None)
    await state.set_state(AircraftWizard.manufacturer)
    await callback.message.edit_text(t("ask_manufacturer", _lang(user)))
    await callback.message.answer("...", reply_markup=skip_cancel_keyboard(_lang(user)))
    await callback.answer()


@router.message(AircraftWizard.manufacturer)
async def got_manufacturer(message: Message, state: FSMContext, user: User) -> None:
    await state.update_data(manufacturer=parse_optional_text(message.text))
    await state.set_state(AircraftWizard.model)
    await message.answer(t("ask_model", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


@router.callback_query(AircraftWizard.manufacturer, F.data == "wizard:skip")
async def skip_manufacturer(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(manufacturer=None)
    await state.set_state(AircraftWizard.model)
    await callback.message.edit_text(t("ask_model", _lang(user)))
    await callback.answer()


@router.message(AircraftWizard.model)
async def got_model(message: Message, state: FSMContext, user: User) -> None:
    model = message.text.strip()
    if not model:
        await message.answer(t("error_generic", _lang(user), detail="model required"))
        return
    await state.update_data(model=model)
    await state.set_state(AircraftWizard.empty_weight)
    await message.answer(t("ask_empty_weight", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


@router.message(AircraftWizard.empty_weight)
async def got_empty_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        weight = parse_decimal(message.text)
        if weight <= 0:
            raise InputParseError("must be positive")
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(basic_empty_weight_lb=str(weight))
    await state.set_state(AircraftWizard.cg_or_moment_choice)
    data = await state.get_data()
    await message.answer(
        t("ask_cg_or_moment", lang), reply_markup=cg_or_moment_keyboard(lang, show_keep=bool(data.get("update_mode")))
    )


@router.callback_query(AircraftWizard.empty_weight, F.data == "wizard:keep")
async def keep_empty_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    await state.set_state(AircraftWizard.cg_or_moment_choice)
    await callback.message.edit_text(t("ask_cg_or_moment", lang))
    await callback.message.answer("...", reply_markup=cg_or_moment_keyboard(lang, show_keep=True))
    await callback.answer()


@router.callback_query(AircraftWizard.cg_or_moment_choice, F.data == "wizard:keep_cg_moment")
async def keep_cg_moment(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await _go_to_confirm_empty_record(callback.message, state, user)
    await callback.answer()


@router.callback_query(AircraftWizard.cg_or_moment_choice, F.data == "wizard:know_cg")
async def choose_know_cg(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.set_state(AircraftWizard.empty_cg)
    await callback.message.edit_text(t("ask_empty_cg", _lang(user)))
    await callback.answer()


@router.callback_query(AircraftWizard.cg_or_moment_choice, F.data == "wizard:know_moment")
async def choose_know_moment(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.set_state(AircraftWizard.empty_moment)
    await callback.message.edit_text(t("ask_empty_moment", _lang(user)))
    await callback.answer()


@router.message(AircraftWizard.empty_cg)
async def got_empty_cg(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        cg = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    weight = Decimal(data["basic_empty_weight_lb"])
    moment = weight * cg
    await state.update_data(basic_empty_cg_in=str(cg), basic_empty_moment_lb_in=str(moment))
    await _go_to_confirm_empty_record(message, state, user)


@router.message(AircraftWizard.empty_moment)
async def got_empty_moment(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        moment = parse_decimal(message.text, allow_negative=True)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    weight = Decimal(data["basic_empty_weight_lb"])
    cg = moment / weight
    await state.update_data(basic_empty_cg_in=str(cg), basic_empty_moment_lb_in=str(moment))
    await _go_to_confirm_empty_record(message, state, user)


async def _go_to_confirm_empty_record(message: Message, state: FSMContext, user: User) -> None:
    await state.set_state(AircraftWizard.confirm_empty_record)
    await message.answer(t("confirm_empty_wb_record", _lang(user)), reply_markup=yes_no_keyboard(_lang(user)))


@router.callback_query(AircraftWizard.confirm_empty_record, F.data == "wizard:yes")
async def confirm_empty_record_yes(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await state.set_state(AircraftWizard.max_ramp_weight)
    await callback.message.edit_text(t("ask_max_ramp_weight", lang))
    await callback.message.answer(
        "...", reply_markup=skip_cancel_keyboard(lang, show_keep=bool(data.get("update_mode")))
    )
    await callback.answer()


@router.callback_query(AircraftWizard.confirm_empty_record, F.data == "wizard:no")
async def confirm_empty_record_no(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await callback.message.edit_text(t("cancelled", lang))
    await callback.message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))
    await callback.answer()


async def _optional_weight_step(
    message_or_callback, state: FSMContext, user: User, field: str, next_state, next_prompt_key: str
) -> None:
    pass


@router.message(AircraftWizard.max_ramp_weight)
async def got_max_ramp_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(max_ramp_weight_lb=str(value) if value is not None else None)
    await _advance_to_max_takeoff(message, state, user)


@router.callback_query(AircraftWizard.max_ramp_weight, F.data == "wizard:skip")
async def skip_max_ramp_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(max_ramp_weight_lb=None)
    await _advance_to_max_takeoff(callback.message, state, user)
    await callback.answer()


@router.callback_query(AircraftWizard.max_ramp_weight, F.data == "wizard:keep")
async def keep_max_ramp_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await _advance_to_max_takeoff(callback.message, state, user)
    await callback.answer()


async def _advance_to_max_takeoff(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await state.set_state(AircraftWizard.max_takeoff_weight)
    await message.answer(
        t("ask_max_takeoff_weight", lang),
        reply_markup=keep_cancel_keyboard(lang, show_keep=bool(data.get("update_mode"))),
    )


@router.message(AircraftWizard.max_takeoff_weight)
async def got_max_takeoff_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text)
        if value <= 0:
            raise InputParseError("must be positive")
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(max_takeoff_weight_lb=str(value))
    await _advance_to_max_landing(message, state, user)


@router.callback_query(AircraftWizard.max_takeoff_weight, F.data == "wizard:keep")
async def keep_max_takeoff_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await _advance_to_max_landing(callback.message, state, user)
    await callback.answer()


async def _advance_to_max_landing(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await state.set_state(AircraftWizard.max_landing_weight)
    await message.answer(
        t("ask_max_landing_weight", lang),
        reply_markup=skip_cancel_keyboard(lang, show_keep=bool(data.get("update_mode"))),
    )


@router.message(AircraftWizard.max_landing_weight)
async def got_max_landing_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(max_landing_weight_lb=str(value) if value is not None else None)
    await _advance_to_max_zfw(message, state, user)


@router.callback_query(AircraftWizard.max_landing_weight, F.data == "wizard:skip")
async def skip_max_landing_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(max_landing_weight_lb=None)
    await _advance_to_max_zfw(callback.message, state, user)
    await callback.answer()


@router.callback_query(AircraftWizard.max_landing_weight, F.data == "wizard:keep")
async def keep_max_landing_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await _advance_to_max_zfw(callback.message, state, user)
    await callback.answer()


async def _advance_to_max_zfw(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await state.set_state(AircraftWizard.max_zfw)
    await message.answer(
        t("ask_max_zfw", lang), reply_markup=skip_cancel_keyboard(lang, show_keep=bool(data.get("update_mode")))
    )


@router.message(AircraftWizard.max_zfw)
async def got_max_zfw(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(max_zero_fuel_weight_lb=str(value) if value is not None else None)
    await _advance_to_useful_load(message, state, user)


@router.callback_query(AircraftWizard.max_zfw, F.data == "wizard:skip")
async def skip_max_zfw(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(max_zero_fuel_weight_lb=None)
    await _advance_to_useful_load(callback.message, state, user)
    await callback.answer()


@router.callback_query(AircraftWizard.max_zfw, F.data == "wizard:keep")
async def keep_max_zfw(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await _advance_to_useful_load(callback.message, state, user)
    await callback.answer()


async def _advance_to_useful_load(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await state.set_state(AircraftWizard.known_useful_load)
    await message.answer(
        t("ask_known_useful_load", lang),
        reply_markup=skip_cancel_keyboard(lang, show_keep=bool(data.get("update_mode"))),
    )


async def _finish_useful_load(message: Message, state: FSMContext, user: User, value: Decimal | None) -> None:
    lang = _lang(user)
    await state.update_data(known_useful_load_lb=str(value) if value is not None else None)
    data = await state.get_data()
    if value is not None:
        draft_probe = AircraftRevisionDraft(
            basic_empty_weight_lb=Decimal(data["basic_empty_weight_lb"]),
            basic_empty_moment_lb_in=Decimal(data["basic_empty_moment_lb_in"]),
            basic_empty_cg_in=Decimal(data["basic_empty_cg_in"]),
            max_takeoff_weight_lb=Decimal(data["max_takeoff_weight_lb"]),
            stations=[],
            envelope_rows=[],
            known_useful_load_lb=value,
        )
        warning = useful_load_warning(draft_probe)
        if warning:
            await message.answer(f"⚠️ {warning}")
        else:
            await message.answer(t("useful_load_ok", lang))
    await state.set_state(AircraftWizard.station_add_prompt)
    await message.answer(t("ask_add_station", lang), reply_markup=yes_no_keyboard(lang))


@router.message(AircraftWizard.known_useful_load)
async def got_known_useful_load(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await _finish_useful_load(message, state, user, value)


@router.callback_query(AircraftWizard.known_useful_load, F.data == "wizard:skip")
async def skip_known_useful_load(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await callback.message.delete_reply_markup()
    await _finish_useful_load(callback.message, state, user, None)


@router.callback_query(AircraftWizard.known_useful_load, F.data == "wizard:keep")
async def keep_known_useful_load(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    data = await state.get_data()
    existing = data.get("known_useful_load_lb")
    await _finish_useful_load(
        callback.message, state, user, Decimal(existing) if existing is not None else None
    )


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------


@router.callback_query(AircraftWizard.station_add_prompt, F.data == "wizard:yes")
async def add_station_yes(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.set_state(AircraftWizard.station_name)
    await callback.message.edit_text(t("ask_station_name", _lang(user)))
    await callback.answer()


@router.callback_query(F.data == "wizard:add_station")
async def add_another_station(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.set_state(AircraftWizard.station_name)
    await callback.message.edit_text(t("ask_station_name", _lang(user)))
    await callback.answer()


@router.callback_query(AircraftWizard.station_add_prompt, F.data == "wizard:no")
@router.callback_query(F.data == "wizard:stations_done")
async def stations_done(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.set_state(AircraftWizard.envelope_rows)
    await callback.message.edit_text(
        "Enter CG envelope rows, one per message, as: weight, forward_limit, aft_limit\n"
        "Example format only (not real data): 2200, 35.0, 47.3\n\n"
        "Send at least two rows in increasing weight order, then press Done.",
    )
    await callback.message.answer("...", reply_markup=_envelope_keyboard(_lang(user)))
    await callback.answer()


def _envelope_keyboard(lang: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Done", callback_data="wizard:envelope_done")],
            [InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel")],
        ]
    )


@router.message(AircraftWizard.station_name)
async def got_station_name(message: Message, state: FSMContext, user: User) -> None:
    name = message.text.strip()
    if not name:
        await message.answer(t("error_generic", _lang(user), detail="name required"))
        return
    await state.update_data(current_station_name=name)
    await state.set_state(AircraftWizard.station_type)
    await message.answer(t("ask_station_type", _lang(user)), reply_markup=station_type_keyboard())


@router.callback_query(AircraftWizard.station_type, F.data.startswith("stype:"))
async def got_station_type(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    station_type = callback.data.split(":", 1)[1]
    await state.update_data(current_station_type=station_type)
    await state.set_state(AircraftWizard.station_arm)
    await callback.message.edit_text(t("ask_station_arm", _lang(user)))
    await callback.answer()


@router.message(AircraftWizard.station_arm)
async def got_station_arm(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        arm = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(current_station_arm=str(arm))
    await state.set_state(AircraftWizard.station_arm_mode)
    await message.answer(t("ask_station_arm_fixed_or_adjustable", lang), reply_markup=arm_fixed_adjustable_keyboard(lang))


async def _continue_after_arm_mode(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    station_type = data["current_station_type"]
    lang = _lang(user)
    if station_type == StationType.FUEL.value:
        await state.set_state(AircraftWizard.station_fuel_max_volume)
        await callback.message.answer(t("ask_fuel_max_volume", lang), reply_markup=cancel_only_keyboard(lang))
    else:
        await state.set_state(AircraftWizard.station_max_weight)
        await callback.message.answer(t("ask_station_max_weight", lang), reply_markup=skip_cancel_keyboard(lang))


@router.callback_query(AircraftWizard.station_arm_mode, F.data == "wizard:arm_fixed")
async def arm_fixed(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(current_station_adjustable=False, current_station_min_arm=None, current_station_max_arm=None)
    await callback.message.edit_text("ARM: fixed.")
    await _continue_after_arm_mode(callback, state, user)
    await callback.answer()


@router.callback_query(AircraftWizard.station_arm_mode, F.data == "wizard:arm_adjustable")
async def arm_adjustable(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(current_station_adjustable=True)
    await state.set_state(AircraftWizard.station_min_arm)
    await callback.message.edit_text(t("ask_station_min_arm", _lang(user)))
    await callback.answer()


@router.message(AircraftWizard.station_min_arm)
async def got_station_min_arm(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(current_station_min_arm=str(value))
    await state.set_state(AircraftWizard.station_max_arm)
    await message.answer(t("ask_station_max_arm", lang), reply_markup=cancel_only_keyboard(lang))


@router.message(AircraftWizard.station_max_arm)
async def got_station_max_arm(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    min_arm = Decimal(data["current_station_min_arm"])
    if value < min_arm:
        await message.answer(t("error_generic", lang, detail="max ARM must be >= min ARM"))
        return
    await state.update_data(current_station_max_arm=str(value))
    data = await state.get_data()
    station_type = data["current_station_type"]
    if station_type == StationType.FUEL.value:
        await state.set_state(AircraftWizard.station_fuel_max_volume)
        await message.answer(t("ask_fuel_max_volume", lang), reply_markup=cancel_only_keyboard(lang))
    else:
        await state.set_state(AircraftWizard.station_max_weight)
        await message.answer(t("ask_station_max_weight", lang), reply_markup=skip_cancel_keyboard(lang))


@router.message(AircraftWizard.station_max_weight)
async def got_station_max_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await _finalize_station(message, state, user, max_weight=value)


@router.callback_query(AircraftWizard.station_max_weight, F.data == "wizard:skip")
async def skip_station_max_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _finalize_station(callback.message, state, user, max_weight=None)


@router.message(AircraftWizard.station_fuel_max_volume)
async def got_fuel_max_volume(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text)
        if value <= 0:
            raise InputParseError("must be positive")
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(current_station_fuel_max_volume=str(value))
    await state.set_state(AircraftWizard.station_fuel_density)
    await message.answer(t("ask_fuel_density", lang), reply_markup=cancel_only_keyboard(lang))


@router.message(AircraftWizard.station_fuel_density)
async def got_fuel_density(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text)
        if value <= 0:
            raise InputParseError("must be positive")
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    max_volume = Decimal(data["current_station_fuel_max_volume"])
    await _finalize_station(message, state, user, max_weight=None, fuel_max_volume=max_volume, fuel_density=value)


async def _finalize_station(
    message: Message,
    state: FSMContext,
    user: User,
    *,
    max_weight: Decimal | None,
    fuel_max_volume: Decimal | None = None,
    fuel_density: Decimal | None = None,
) -> None:
    lang = _lang(user)
    data = await state.get_data()
    station = {
        "name": data["current_station_name"],
        "station_type": data["current_station_type"],
        "default_arm_in": data["current_station_arm"],
        "is_adjustable_arm": data.get("current_station_adjustable", False),
        "minimum_arm_in": data.get("current_station_min_arm"),
        "maximum_arm_in": data.get("current_station_max_arm"),
        "maximum_weight_lb": str(max_weight) if max_weight is not None else None,
        "maximum_volume_gal": str(fuel_max_volume) if fuel_max_volume is not None else None,
        "fuel_density_lb_per_gal": str(fuel_density) if fuel_density is not None else None,
    }
    stations = data.get("stations", [])
    stations.append(station)
    await state.update_data(
        stations=stations,
        current_station_name=None,
        current_station_type=None,
        current_station_arm=None,
        current_station_adjustable=None,
        current_station_min_arm=None,
        current_station_max_arm=None,
        current_station_fuel_max_volume=None,
    )
    await state.set_state(AircraftWizard.station_add_prompt)
    await message.answer(
        f"Station \"{station['name']}\" added.", reply_markup=add_another_station_keyboard(lang)
    )


# ---------------------------------------------------------------------------
# CG envelope
# ---------------------------------------------------------------------------


@router.message(AircraftWizard.envelope_rows)
async def got_envelope_row(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    parts = [p.strip() for p in message.text.replace(";", ",").split(",")]
    if len(parts) != 3:
        await message.answer(
            t("error_generic", lang, detail="expected: weight, forward_limit, aft_limit")
        )
        return
    try:
        weight = parse_decimal(parts[0])
        forward = parse_decimal(parts[1])
        aft = parse_decimal(parts[2])
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    rows = data.get("envelope_rows", [])
    rows.append({"weight_lb": str(weight), "forward_cg_limit_in": str(forward), "aft_cg_limit_in": str(aft)})
    await state.update_data(envelope_rows=rows)
    await message.answer(f"Row added ({len(rows)} so far). Send another, or press Done.")


@router.callback_query(AircraftWizard.envelope_rows, F.data == "wizard:envelope_done")
async def envelope_done(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    rows = data.get("envelope_rows", [])
    try:
        CGEnvelope(
            [
                EnvelopeRow(Decimal(r["weight_lb"]), Decimal(r["forward_cg_limit_in"]), Decimal(r["aft_cg_limit_in"]))
                for r in rows
            ]
        )
    except InvalidEnvelopeError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    data = await state.get_data()
    await state.set_state(AircraftWizard.source_doc_name)
    await callback.message.edit_text(t("ask_source_doc_name", lang))
    await callback.message.answer(
        "...", reply_markup=skip_cancel_keyboard(lang, show_keep=bool(data.get("update_mode")))
    )
    await callback.answer()


@router.message(AircraftWizard.source_doc_name)
async def got_source_doc_name(message: Message, state: FSMContext, user: User) -> None:
    await state.update_data(source_document_name=parse_optional_text(message.text))
    await _advance_to_source_doc_date(message, state, user)


@router.callback_query(AircraftWizard.source_doc_name, F.data == "wizard:skip")
async def skip_source_doc_name(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(source_document_name=None)
    await _advance_to_source_doc_date(callback.message, state, user)
    await callback.answer()


@router.callback_query(AircraftWizard.source_doc_name, F.data == "wizard:keep")
async def keep_source_doc_name(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await _advance_to_source_doc_date(callback.message, state, user)
    await callback.answer()


async def _advance_to_source_doc_date(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await state.set_state(AircraftWizard.source_doc_date)
    await message.answer(
        t("ask_source_doc_date", lang), reply_markup=skip_cancel_keyboard(lang, show_keep=bool(data.get("update_mode")))
    )


@router.message(AircraftWizard.source_doc_date)
async def got_source_doc_date(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_date(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(source_document_date=value.isoformat() if value else None)
    await _show_review(message, state, user)


@router.callback_query(AircraftWizard.source_doc_date, F.data == "wizard:skip")
async def skip_source_doc_date(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(source_document_date=None)
    await callback.answer()
    await _show_review(callback.message, state, user)


@router.callback_query(AircraftWizard.source_doc_date, F.data == "wizard:keep")
async def keep_source_doc_date(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _show_review(callback.message, state, user)


def build_draft_from_state_data(data: dict) -> AircraftRevisionDraft:
    stations = [
        StationDraft(
            name=s["name"],
            station_type=StationType(s["station_type"]),
            default_arm_in=Decimal(s["default_arm_in"]),
            is_adjustable_arm=s["is_adjustable_arm"],
            minimum_arm_in=Decimal(s["minimum_arm_in"]) if s.get("minimum_arm_in") else None,
            maximum_arm_in=Decimal(s["maximum_arm_in"]) if s.get("maximum_arm_in") else None,
            maximum_weight_lb=Decimal(s["maximum_weight_lb"]) if s.get("maximum_weight_lb") else None,
            maximum_volume_gal=Decimal(s["maximum_volume_gal"]) if s.get("maximum_volume_gal") else None,
            fuel_density_lb_per_gal=Decimal(s["fuel_density_lb_per_gal"]) if s.get("fuel_density_lb_per_gal") else None,
        )
        for s in data.get("stations", [])
    ]
    envelope_rows = [
        EnvelopeRowDraft(Decimal(r["weight_lb"]), Decimal(r["forward_cg_limit_in"]), Decimal(r["aft_cg_limit_in"]))
        for r in data.get("envelope_rows", [])
    ]
    import datetime as _dt

    return AircraftRevisionDraft(
        basic_empty_weight_lb=Decimal(data["basic_empty_weight_lb"]),
        basic_empty_moment_lb_in=Decimal(data["basic_empty_moment_lb_in"]),
        basic_empty_cg_in=Decimal(data["basic_empty_cg_in"]),
        max_takeoff_weight_lb=Decimal(data["max_takeoff_weight_lb"]),
        stations=stations,
        envelope_rows=envelope_rows,
        max_ramp_weight_lb=Decimal(data["max_ramp_weight_lb"]) if data.get("max_ramp_weight_lb") else None,
        max_landing_weight_lb=Decimal(data["max_landing_weight_lb"]) if data.get("max_landing_weight_lb") else None,
        max_zero_fuel_weight_lb=Decimal(data["max_zero_fuel_weight_lb"]) if data.get("max_zero_fuel_weight_lb") else None,
        known_useful_load_lb=Decimal(data["known_useful_load_lb"]) if data.get("known_useful_load_lb") else None,
        source_document_name=data.get("source_document_name"),
        source_document_date=_dt.date.fromisoformat(data["source_document_date"]) if data.get("source_document_date") else None,
        notes=None,
    )


def render_summary(data: dict, lang: str) -> str:
    lines = [t("review_aircraft_summary", lang), ""]
    lines.append(f"Tail number: {data.get('tail_number')}")
    if data.get("nickname"):
        lines.append(f"Nickname: {data['nickname']}")
    if data.get("manufacturer"):
        lines.append(f"Manufacturer: {data['manufacturer']}")
    lines.append(f"Model: {data.get('model')}")
    lines.append(f"Basic Empty Weight: {fmt(Decimal(data['basic_empty_weight_lb']), ' lb')}")
    lines.append(f"Basic Empty CG: {fmt(Decimal(data['basic_empty_cg_in']), ' in')}")
    lines.append(f"Basic Empty Moment: {fmt(Decimal(data['basic_empty_moment_lb_in']), ' lb-in')}")
    lines.append(
        f"Max Ramp Weight: {fmt(Decimal(data['max_ramp_weight_lb']), ' lb') if data.get('max_ramp_weight_lb') else 'not set'}"
    )
    lines.append(f"Max Takeoff Weight: {fmt(Decimal(data['max_takeoff_weight_lb']), ' lb')}")
    lines.append(
        f"Max Landing Weight: {fmt(Decimal(data['max_landing_weight_lb']), ' lb') if data.get('max_landing_weight_lb') else 'not set'}"
    )
    lines.append(
        f"Max Zero Fuel Weight: {fmt(Decimal(data['max_zero_fuel_weight_lb']), ' lb') if data.get('max_zero_fuel_weight_lb') else 'not set'}"
    )
    lines.append(f"Stations ({len(data.get('stations', []))}):")
    for s in data.get("stations", []):
        lines.append(f"  - {s['name']} ({s['station_type']}), ARM {s['default_arm_in']} in")
    lines.append(f"CG envelope rows ({len(data.get('envelope_rows', []))}):")
    for r in data.get("envelope_rows", []):
        lines.append(f"  - {r['weight_lb']} lb: {r['forward_cg_limit_in']}-{r['aft_cg_limit_in']} in")
    return "\n".join(lines)


async def _show_review(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await state.set_state(AircraftWizard.review)
    await message.answer(render_summary(data, lang), reply_markup=confirm_keyboard(lang))


@router.callback_query(AircraftWizard.review, F.data == "wizard:confirm")
async def review_confirm(
    callback: CallbackQuery, state: FSMContext, user: User, aircraft_service: AircraftService
) -> None:
    lang = _lang(user)
    data = await state.get_data()
    try:
        draft = build_draft_from_state_data(data)
    except InvalidEnvelopeError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    if data.get("update_mode"):
        aircraft = await aircraft_service.get_aircraft(user.id, data["aircraft_id"])
        if aircraft is None:
            await callback.answer("Aircraft not found.", show_alert=True)
            await state.clear()
            return
        await aircraft_service.update_aircraft(aircraft, draft)
        await state.clear()
        await callback.message.edit_text(t("revision_saved", lang))
        await callback.message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))
        await callback.answer()
        return

    await aircraft_service.create_aircraft(
        user.id, data["tail_number"], data["model"], data.get("nickname"), data.get("manufacturer"), draft
    )
    await state.clear()
    await callback.message.edit_text(t("aircraft_saved", lang))
    await callback.message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))
    await callback.answer()


@router.callback_query(AircraftWizard.review, F.data == "wizard:edit")
async def review_edit(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    await state.update_data(stations=[], envelope_rows=[])
    await state.set_state(AircraftWizard.tail_number)
    await callback.message.edit_text(t("ask_tail_number", lang))
    await callback.answer()
