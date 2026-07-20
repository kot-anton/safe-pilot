"""Aircraft creation wizard. Pure Telegram presentation glue -- all math happens in app.domain
and app.services; this file only collects and validates user input step by step.

Navigation: every forward step goes through `goto()` (app.bot.handlers.wizard_nav), which
records the state being left. A "◀ Back" button on (almost) every screen calls `go_back()`,
which pops that history and re-renders the previous screen from whatever is already in FSM
data -- so a wrong answer is always recoverable without restarting the whole wizard.
Stations and CG envelope rows are list-building steps instead: rather than step-by-step
Back, they offer "remove last" / "undo last row", since nothing is otherwise committed
until the entry is finalized.
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.handlers._common import (
    InputParseError,
    fmt,
    parse_decimal,
    parse_optional_date,
    parse_optional_decimal,
    parse_optional_text,
)
from app.bot.handlers.wizard_nav import goto, go_back
from app.bot.keyboards.common import (
    STATION_TYPE_DEFAULT_NAMES,
    arm_fixed_adjustable_keyboard,
    cancel_only_keyboard,
    cg_or_moment_keyboard,
    confirm_keyboard,
    envelope_keyboard,
    keep_cancel_keyboard,
    main_menu_keyboard,
    skip_cancel_keyboard,
    station_name_keyboard,
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
    AircraftService,
    EnvelopeRowDraft,
    StationDraft,
    useful_load_warning,
)

router = Router(name="aircraft_wizard")


def _lang(user: User) -> str:
    return user.language or "en"


def _is_update(data: dict) -> bool:
    return bool(data.get("update_mode"))


# ---------------------------------------------------------------------------
# Step renderers -- each one is the single source of truth for how a step is
# displayed, so `goto()` (moving forward) and `go_back()` (moving backward)
# always show an identical screen.
# ---------------------------------------------------------------------------


async def render_tail_number(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_tail_number", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user), show_back=False))


async def render_nickname(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_nickname", _lang(user)), reply_markup=skip_cancel_keyboard(_lang(user)))


async def render_manufacturer(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_manufacturer", _lang(user)), reply_markup=skip_cancel_keyboard(_lang(user)))


async def render_model(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_model", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


async def render_empty_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    suffix = f"\n(current: {data['basic_empty_weight_lb']} lb)" if data.get("basic_empty_weight_lb") else ""
    await message.answer(
        t("ask_empty_weight", lang) + suffix,
        reply_markup=keep_cancel_keyboard(lang, show_keep=_is_update(data)),
    )


async def render_cg_or_moment_choice(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(t("ask_cg_or_moment", lang), reply_markup=cg_or_moment_keyboard(lang, show_keep=_is_update(data)))


async def render_empty_cg(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_empty_cg", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


async def render_empty_moment(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_empty_moment", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


async def render_confirm_empty_record(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("confirm_empty_wb_record", _lang(user)), reply_markup=yes_no_keyboard(_lang(user)))


async def render_max_ramp_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(t("ask_max_ramp_weight", lang), reply_markup=skip_cancel_keyboard(lang, show_keep=_is_update(data)))


async def render_max_takeoff_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(t("ask_max_takeoff_weight", lang), reply_markup=keep_cancel_keyboard(lang, show_keep=_is_update(data)))


async def render_max_landing_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(t("ask_max_landing_weight", lang), reply_markup=skip_cancel_keyboard(lang, show_keep=_is_update(data)))


async def render_max_zfw(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(t("ask_max_zfw", lang), reply_markup=skip_cancel_keyboard(lang, show_keep=_is_update(data)))


async def render_known_useful_load(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(t("ask_known_useful_load", lang), reply_markup=skip_cancel_keyboard(lang, show_keep=_is_update(data)))


async def render_station_add_prompt(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    stations = data.get("stations", [])
    rows = [
        [
            InlineKeyboardButton(text=t("btn_yes", lang), callback_data="wizard:yes"),
            InlineKeyboardButton(text=t("btn_no", lang), callback_data="wizard:no"),
        ]
    ]
    if stations:
        rows.append(
            [InlineKeyboardButton(text=f"🗑 Remove last ({stations[-1]['name']})", callback_data="wizard:remove_last_station")]
        )
    text = t("ask_add_station", lang)
    if stations:
        text += "\n\nAdded so far:\n" + "\n".join(f"- {s['name']}" for s in stations)
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def render_station_type(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    await message.answer(t("ask_station_type", lang), reply_markup=station_type_keyboard(lang))


def _default_station_name(station_type_value: str, stations: list[dict]) -> str:
    base = STATION_TYPE_DEFAULT_NAMES[StationTypeEnum(station_type_value)]
    count = sum(1 for s in stations if s["station_type"] == station_type_value)
    return base if count == 0 else f"{base} {count + 1}"


async def render_station_name(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    default_name = _default_station_name(data["current_station_type"], data.get("stations", []))
    await message.answer(
        f"{t('ask_station_name', lang)}\nOr just use the suggested default below.",
        reply_markup=station_name_keyboard(lang, default_name),
    )


async def render_station_arm(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_station_arm", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


async def render_station_arm_mode(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_station_arm_fixed_or_adjustable", _lang(user)), reply_markup=arm_fixed_adjustable_keyboard(_lang(user)))


async def render_station_min_arm(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_station_min_arm", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


async def render_station_max_arm(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_station_max_arm", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


async def render_station_max_weight(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_station_max_weight", _lang(user)), reply_markup=skip_cancel_keyboard(_lang(user)))


async def render_station_fuel_max_volume(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_fuel_max_volume", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


async def render_station_fuel_density(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_fuel_density", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


async def render_envelope_rows(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    rows = data.get("envelope_rows", [])
    text = (
        "Enter CG envelope rows, one per message, as: weight, forward_limit, aft_limit\n"
        "Example format only (not real data): 2200, 35.0, 47.3\n\n"
        "If your POH only lists a single CG range (not a table that varies by weight), just "
        "enter it as two rows using your aircraft's minimum and maximum weight with the same "
        "forward/aft numbers both times -- that's mathematically the same thing.\n\n"
        "Send at least two rows in increasing weight order, then press Done. If you genuinely "
        "don't have this data yet, you can skip it below -- but then this aircraft's "
        "calculations will only check weight, never CG, until you add it via Update Aircraft."
    )
    if rows:
        text += "\n\nRows so far:\n" + "\n".join(
            f"- {r['weight_lb']} lb: {r['forward_cg_limit_in']}-{r['aft_cg_limit_in']} in" for r in rows
        )
    await message.answer(text, reply_markup=envelope_keyboard(lang, has_rows=bool(rows)))


async def render_source_doc_name(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(t("ask_source_doc_name", lang), reply_markup=skip_cancel_keyboard(lang, show_keep=_is_update(data)))


async def render_source_doc_date(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(t("ask_source_doc_date", lang), reply_markup=skip_cancel_keyboard(lang, show_keep=_is_update(data)))


async def render_review(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(render_summary(data, lang), reply_markup=confirm_keyboard(lang))


RENDERERS: dict[str, "callable"] = {
    AircraftWizard.tail_number.state: render_tail_number,
    AircraftWizard.nickname.state: render_nickname,
    AircraftWizard.manufacturer.state: render_manufacturer,
    AircraftWizard.model.state: render_model,
    AircraftWizard.empty_weight.state: render_empty_weight,
    AircraftWizard.cg_or_moment_choice.state: render_cg_or_moment_choice,
    AircraftWizard.empty_cg.state: render_empty_cg,
    AircraftWizard.empty_moment.state: render_empty_moment,
    AircraftWizard.confirm_empty_record.state: render_confirm_empty_record,
    AircraftWizard.max_ramp_weight.state: render_max_ramp_weight,
    AircraftWizard.max_takeoff_weight.state: render_max_takeoff_weight,
    AircraftWizard.max_landing_weight.state: render_max_landing_weight,
    AircraftWizard.max_zfw.state: render_max_zfw,
    AircraftWizard.known_useful_load.state: render_known_useful_load,
    AircraftWizard.station_add_prompt.state: render_station_add_prompt,
    AircraftWizard.station_type.state: render_station_type,
    AircraftWizard.station_name.state: render_station_name,
    AircraftWizard.station_arm.state: render_station_arm,
    AircraftWizard.station_arm_mode.state: render_station_arm_mode,
    AircraftWizard.station_min_arm.state: render_station_min_arm,
    AircraftWizard.station_max_arm.state: render_station_max_arm,
    AircraftWizard.station_max_weight.state: render_station_max_weight,
    AircraftWizard.station_fuel_max_volume.state: render_station_fuel_max_volume,
    AircraftWizard.station_fuel_density.state: render_station_fuel_density,
    AircraftWizard.envelope_rows.state: render_envelope_rows,
    AircraftWizard.source_doc_name.state: render_source_doc_name,
    AircraftWizard.source_doc_date.state: render_source_doc_date,
    AircraftWizard.review.state: render_review,
}


async def _cannot_go_back(message: Message, state: FSMContext, user: User) -> None:
    await message.answer("Already at the first step of this wizard.")


@router.callback_query(StateFilter(AircraftWizard), F.data == "wizard:back")
async def wizard_back(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await go_back(callback.message, state, user, RENDERERS, _cannot_go_back)
    await callback.answer()


# ---------------------------------------------------------------------------
# Entry point + top-level cancel
# ---------------------------------------------------------------------------


def _setup_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Quick Setup (recommended)", callback_data="wizard:quick_setup")],
            [InlineKeyboardButton(text="🛠 Advanced Setup", callback_data="wizard:advanced_setup")],
        ]
    )


@router.message(F.text.in_({t("menu_add_aircraft", "en"), t("menu_add_aircraft", "ru")}))
async def start_wizard(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    await state.update_data(stations=[], envelope_rows=[])
    await message.answer(
        "Quick Setup asks only what's needed for a valid calculation (empty weight/CG, max "
        "takeoff weight, seats/baggage/fuel, CG envelope). Advanced Setup also covers ramp/"
        "landing/ZFW weights, known useful load, ballast, and source documents.",
        reply_markup=_setup_mode_keyboard(),
    )


@router.callback_query(F.data.in_({"wizard:quick_setup", "wizard:advanced_setup"}))
async def choose_setup_mode(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    setup_mode = "quick" if callback.data == "wizard:quick_setup" else "advanced"
    await state.update_data(setup_mode=setup_mode)
    await callback.answer()
    await goto(callback.message, state, user, AircraftWizard.tail_number, render_tail_number, record_history=False)


@router.message(F.text.in_({t("menu_rental_aircraft", "en"), t("menu_rental_aircraft", "ru")}))
async def start_rental_wizard(message: Message, state: FSMContext, user: User) -> None:
    """Rental aircraft always use Quick Setup -- just flagged as temporary so it can be told
    apart later (e.g. for a future auto-archive pass) without a separate flow to maintain."""
    await state.clear()
    await state.update_data(stations=[], envelope_rows=[], is_temporary=True, setup_mode="quick")
    await message.answer("Setting up a temporary/rental aircraft profile (Quick Setup).")
    await goto(message, state, user, AircraftWizard.tail_number, render_tail_number, record_history=False)


def _is_quick(data: dict) -> bool:
    return data.get("setup_mode") == "quick"


@router.callback_query(F.data == "wizard:cancel")
async def wizard_cancel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await callback.message.answer(t("cancelled", lang), reply_markup=main_menu_keyboard(lang))
    await callback.answer()


# ---------------------------------------------------------------------------
# Identity fields
# ---------------------------------------------------------------------------


@router.message(AircraftWizard.tail_number)
async def got_tail_number(message: Message, state: FSMContext, user: User) -> None:
    tail_number = message.text.strip().upper()
    if not tail_number:
        await message.answer(t("error_generic", _lang(user), detail="tail number required"))
        return
    await state.update_data(tail_number=tail_number)
    data = await state.get_data()
    if _is_quick(data):
        await state.update_data(nickname=None, manufacturer=None)
        await goto(message, state, user, AircraftWizard.model, render_model)
    else:
        await goto(message, state, user, AircraftWizard.nickname, render_nickname)


@router.message(AircraftWizard.nickname)
async def got_nickname(message: Message, state: FSMContext, user: User) -> None:
    await state.update_data(nickname=parse_optional_text(message.text))
    await goto(message, state, user, AircraftWizard.manufacturer, render_manufacturer)


@router.callback_query(AircraftWizard.nickname, F.data == "wizard:skip")
async def skip_nickname(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(nickname=None)
    await goto(callback.message, state, user, AircraftWizard.manufacturer, render_manufacturer)
    await callback.answer()


@router.message(AircraftWizard.manufacturer)
async def got_manufacturer(message: Message, state: FSMContext, user: User) -> None:
    await state.update_data(manufacturer=parse_optional_text(message.text))
    await goto(message, state, user, AircraftWizard.model, render_model)


@router.callback_query(AircraftWizard.manufacturer, F.data == "wizard:skip")
async def skip_manufacturer(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(manufacturer=None)
    await goto(callback.message, state, user, AircraftWizard.model, render_model)
    await callback.answer()


@router.message(AircraftWizard.model)
async def got_model(message: Message, state: FSMContext, user: User) -> None:
    model = message.text.strip()
    if not model:
        await message.answer(t("error_generic", _lang(user), detail="model required"))
        return
    await state.update_data(model=model)
    await goto(message, state, user, AircraftWizard.empty_weight, render_empty_weight)


# ---------------------------------------------------------------------------
# Empty weight / CG / moment
# ---------------------------------------------------------------------------


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
    await goto(message, state, user, AircraftWizard.cg_or_moment_choice, render_cg_or_moment_choice)


@router.callback_query(AircraftWizard.empty_weight, F.data == "wizard:keep")
async def keep_empty_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.cg_or_moment_choice, render_cg_or_moment_choice)
    await callback.answer()


@router.callback_query(AircraftWizard.cg_or_moment_choice, F.data == "wizard:know_cg")
async def choose_know_cg(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.empty_cg, render_empty_cg)
    await callback.answer()


@router.callback_query(AircraftWizard.cg_or_moment_choice, F.data == "wizard:know_moment")
async def choose_know_moment(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.empty_moment, render_empty_moment)
    await callback.answer()


@router.callback_query(AircraftWizard.cg_or_moment_choice, F.data == "wizard:keep_cg_moment")
async def keep_cg_moment(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.confirm_empty_record, render_confirm_empty_record)
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
    await goto(message, state, user, AircraftWizard.confirm_empty_record, render_confirm_empty_record)


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
    await goto(message, state, user, AircraftWizard.confirm_empty_record, render_confirm_empty_record)


@router.callback_query(AircraftWizard.confirm_empty_record, F.data == "wizard:yes")
async def confirm_empty_record_yes(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    if _is_quick(data):
        await state.update_data(
            max_ramp_weight_lb=None,
            max_landing_weight_lb=None,
            max_zero_fuel_weight_lb=None,
            known_useful_load_lb=None,
        )
        await goto(callback.message, state, user, AircraftWizard.max_takeoff_weight, render_max_takeoff_weight)
    else:
        await goto(callback.message, state, user, AircraftWizard.max_ramp_weight, render_max_ramp_weight)
    await callback.answer()


@router.callback_query(AircraftWizard.confirm_empty_record, F.data == "wizard:no")
async def confirm_empty_record_no(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    # Declining means the empty weight/CG/moment doesn't match their actual W&B record --
    # send them back to fix the number rather than discarding the whole wizard.
    await callback.message.answer(
        "Let's fix that -- please re-enter the empty weight and CG/moment so they match your "
        "aircraft's current Weight & Balance record."
    )
    await go_back(callback.message, state, user, RENDERERS, _cannot_go_back)
    await callback.answer()


# ---------------------------------------------------------------------------
# Scalar weight limits + useful load
# ---------------------------------------------------------------------------


@router.message(AircraftWizard.max_ramp_weight)
async def got_max_ramp_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(max_ramp_weight_lb=str(value) if value is not None else None)
    await goto(message, state, user, AircraftWizard.max_takeoff_weight, render_max_takeoff_weight)


@router.callback_query(AircraftWizard.max_ramp_weight, F.data == "wizard:skip")
async def skip_max_ramp_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(max_ramp_weight_lb=None)
    await goto(callback.message, state, user, AircraftWizard.max_takeoff_weight, render_max_takeoff_weight)
    await callback.answer()


@router.callback_query(AircraftWizard.max_ramp_weight, F.data == "wizard:keep")
async def keep_max_ramp_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.max_takeoff_weight, render_max_takeoff_weight)
    await callback.answer()


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
    await _advance_past_max_takeoff(message, state, user)


@router.callback_query(AircraftWizard.max_takeoff_weight, F.data == "wizard:keep")
async def keep_max_takeoff_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await _advance_past_max_takeoff(callback.message, state, user)
    await callback.answer()


async def _advance_past_max_takeoff(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    if _is_quick(data):
        await goto(message, state, user, AircraftWizard.station_add_prompt, render_station_add_prompt)
    else:
        await goto(message, state, user, AircraftWizard.max_landing_weight, render_max_landing_weight)


@router.message(AircraftWizard.max_landing_weight)
async def got_max_landing_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(max_landing_weight_lb=str(value) if value is not None else None)
    await goto(message, state, user, AircraftWizard.max_zfw, render_max_zfw)


@router.callback_query(AircraftWizard.max_landing_weight, F.data == "wizard:skip")
async def skip_max_landing_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(max_landing_weight_lb=None)
    await goto(callback.message, state, user, AircraftWizard.max_zfw, render_max_zfw)
    await callback.answer()


@router.callback_query(AircraftWizard.max_landing_weight, F.data == "wizard:keep")
async def keep_max_landing_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.max_zfw, render_max_zfw)
    await callback.answer()


@router.message(AircraftWizard.max_zfw)
async def got_max_zfw(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(max_zero_fuel_weight_lb=str(value) if value is not None else None)
    await goto(message, state, user, AircraftWizard.known_useful_load, render_known_useful_load)


@router.callback_query(AircraftWizard.max_zfw, F.data == "wizard:skip")
async def skip_max_zfw(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(max_zero_fuel_weight_lb=None)
    await goto(callback.message, state, user, AircraftWizard.known_useful_load, render_known_useful_load)
    await callback.answer()


@router.callback_query(AircraftWizard.max_zfw, F.data == "wizard:keep")
async def keep_max_zfw(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.known_useful_load, render_known_useful_load)
    await callback.answer()


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
    await goto(message, state, user, AircraftWizard.station_add_prompt, render_station_add_prompt)


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
    await _finish_useful_load(callback.message, state, user, None)


@router.callback_query(AircraftWizard.known_useful_load, F.data == "wizard:keep")
async def keep_known_useful_load(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    data = await state.get_data()
    existing = data.get("known_useful_load_lb")
    await _finish_useful_load(callback.message, state, user, Decimal(existing) if existing is not None else None)


# ---------------------------------------------------------------------------
# Stations -- type first, then a pre-filled default name
# ---------------------------------------------------------------------------


@router.callback_query(AircraftWizard.station_add_prompt, F.data == "wizard:yes")
async def add_station(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.station_type, render_station_type)
    await callback.answer()


@router.callback_query(AircraftWizard.station_add_prompt, F.data == "wizard:remove_last_station")
async def remove_last_station(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    stations = data.get("stations", [])
    if stations:
        removed = stations.pop()
        await state.update_data(stations=stations)
        await callback.answer(f"Removed {removed['name']}.")
    else:
        await callback.answer()
    await render_station_add_prompt(callback.message, state, user)


@router.callback_query(AircraftWizard.station_add_prompt, F.data == "wizard:no")
async def stations_done(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.envelope_rows, render_envelope_rows)
    await callback.answer()


@router.callback_query(AircraftWizard.station_type, F.data.startswith("stype:"))
async def got_station_type(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    station_type = callback.data.split(":", 1)[1]
    await state.update_data(current_station_type=station_type)
    await goto(callback.message, state, user, AircraftWizard.station_name, render_station_name)
    await callback.answer()


@router.message(AircraftWizard.station_name)
async def got_station_name(message: Message, state: FSMContext, user: User) -> None:
    name = message.text.strip()
    if not name:
        await message.answer(t("error_generic", _lang(user), detail="name required"))
        return
    await state.update_data(current_station_name=name)
    await goto(message, state, user, AircraftWizard.station_arm, render_station_arm)


@router.callback_query(AircraftWizard.station_name, F.data == "wizard:use_default_name")
async def use_default_station_name(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    default_name = _default_station_name(data["current_station_type"], data.get("stations", []))
    await state.update_data(current_station_name=default_name)
    await goto(callback.message, state, user, AircraftWizard.station_arm, render_station_arm)
    await callback.answer()


# Only ballast/custom stations are ever asked whether their ARM is adjustable -- seats,
# baggage compartments, and fuel tanks are physically fixed locations in the airframe.
_ADJUSTABLE_ARM_ELIGIBLE = {StationType.BALLAST.value, StationType.CUSTOM.value}


@router.message(AircraftWizard.station_arm)
async def got_station_arm(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        arm = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(current_station_arm=str(arm))
    data = await state.get_data()
    if data["current_station_type"] in _ADJUSTABLE_ARM_ELIGIBLE:
        await goto(message, state, user, AircraftWizard.station_arm_mode, render_station_arm_mode)
    else:
        await state.update_data(current_station_adjustable=False, current_station_min_arm=None, current_station_max_arm=None)
        await _after_arm_configured(message, state, user)


async def _after_arm_configured(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    if data["current_station_type"] == StationType.FUEL.value:
        await goto(message, state, user, AircraftWizard.station_fuel_max_volume, render_station_fuel_max_volume)
    else:
        await goto(message, state, user, AircraftWizard.station_max_weight, render_station_max_weight)


@router.callback_query(AircraftWizard.station_arm_mode, F.data == "wizard:arm_fixed")
async def arm_fixed(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(current_station_adjustable=False, current_station_min_arm=None, current_station_max_arm=None)
    await callback.answer()
    await _after_arm_configured(callback.message, state, user)


@router.callback_query(AircraftWizard.station_arm_mode, F.data == "wizard:arm_adjustable")
async def arm_adjustable(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(current_station_adjustable=True)
    await goto(callback.message, state, user, AircraftWizard.station_min_arm, render_station_min_arm)
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
    await goto(message, state, user, AircraftWizard.station_max_arm, render_station_max_arm)


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
    await _after_arm_configured(message, state, user)


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
    await goto(message, state, user, AircraftWizard.station_fuel_density, render_station_fuel_density)


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
    # Fresh hub screen (not goto/history -- the station is now committed, so Back should not
    # be able to re-open a finalized station's fields and re-append a duplicate).
    await state.set_state(AircraftWizard.station_add_prompt)
    await message.answer(f"Station \"{station['name']}\" added.")
    await render_station_add_prompt(message, state, user)


# ---------------------------------------------------------------------------
# CG envelope
# ---------------------------------------------------------------------------


@router.message(AircraftWizard.envelope_rows)
async def got_envelope_row(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    parts = [p.strip() for p in message.text.replace(";", ",").split(",")]
    if len(parts) != 3:
        await message.answer(t("error_generic", lang, detail="expected: weight, forward_limit, aft_limit"))
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
    await render_envelope_rows(message, state, user)


@router.callback_query(AircraftWizard.envelope_rows, F.data == "wizard:undo_last_row")
async def undo_last_row(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    rows = data.get("envelope_rows", [])
    if rows:
        rows.pop()
        await state.update_data(envelope_rows=rows)
        await callback.answer("Last row removed.")
    else:
        await callback.answer()
    await render_envelope_rows(callback.message, state, user)


@router.callback_query(AircraftWizard.envelope_rows, F.data == "wizard:skip_envelope")
async def skip_envelope(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(envelope_rows=[])
    await callback.answer()
    await callback.message.answer(
        "⚠️ CG envelope skipped. Calculations for this aircraft will check weight limits only "
        "-- CG will show as NOT EVALUATED until you add an envelope via Update Aircraft."
    )
    await _advance_past_envelope(callback.message, state, user)


async def _advance_past_envelope(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    if _is_quick(data):
        await state.update_data(source_document_name=None, source_document_date=None)
        await goto(message, state, user, AircraftWizard.review, render_review)
    else:
        await goto(message, state, user, AircraftWizard.source_doc_name, render_source_doc_name)


@router.callback_query(AircraftWizard.envelope_rows, F.data == "wizard:envelope_done")
async def envelope_done(callback: CallbackQuery, state: FSMContext, user: User) -> None:
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

    await _advance_past_envelope(callback.message, state, user)
    await callback.answer()


@router.message(AircraftWizard.source_doc_name)
async def got_source_doc_name(message: Message, state: FSMContext, user: User) -> None:
    await state.update_data(source_document_name=parse_optional_text(message.text))
    await goto(message, state, user, AircraftWizard.source_doc_date, render_source_doc_date)


@router.callback_query(AircraftWizard.source_doc_name, F.data == "wizard:skip")
async def skip_source_doc_name(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(source_document_name=None)
    await goto(callback.message, state, user, AircraftWizard.source_doc_date, render_source_doc_date)
    await callback.answer()


@router.callback_query(AircraftWizard.source_doc_name, F.data == "wizard:keep")
async def keep_source_doc_name(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.source_doc_date, render_source_doc_date)
    await callback.answer()


@router.message(AircraftWizard.source_doc_date)
async def got_source_doc_date(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_date(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(source_document_date=value.isoformat() if value else None)
    await goto(message, state, user, AircraftWizard.review, render_review)


@router.callback_query(AircraftWizard.source_doc_date, F.data == "wizard:skip")
async def skip_source_doc_date(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(source_document_date=None)
    await goto(callback.message, state, user, AircraftWizard.review, render_review)
    await callback.answer()


@router.callback_query(AircraftWizard.source_doc_date, F.data == "wizard:keep")
async def keep_source_doc_date(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.review, render_review)
    await callback.answer()


# ---------------------------------------------------------------------------
# Review + save
# ---------------------------------------------------------------------------


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
    envelope_rows = data.get("envelope_rows", [])
    if envelope_rows:
        lines.append(f"CG envelope rows ({len(envelope_rows)}):")
        for r in envelope_rows:
            lines.append(f"  - {r['weight_lb']} lb: {r['forward_cg_limit_in']}-{r['aft_cg_limit_in']} in")
    else:
        lines.append("CG envelope: none entered -- CG will NOT be evaluated for this aircraft.")
    return "\n".join(lines)


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
        await callback.message.answer(t("revision_saved", lang), reply_markup=main_menu_keyboard(lang))
        await callback.answer()
        return

    await aircraft_service.create_aircraft(
        user.id,
        data["tail_number"],
        data["model"],
        data.get("nickname"),
        data.get("manufacturer"),
        draft,
        is_temporary=bool(data.get("is_temporary")),
    )
    await state.clear()
    await callback.message.answer(t("aircraft_saved", lang), reply_markup=main_menu_keyboard(lang))
    await callback.answer()
