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
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

from app.bot.handlers._common import (
    InputParseError,
    fmt,
    parse_decimal,
    parse_optional_decimal,
    parse_optional_text,
)
from app.bot.handlers.wizard_nav import goto, go_back
from app.bot.keyboards.common import (
    STATION_TYPE_TEXT_KEYS,
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
)
from app.bot.states.aircraft_wizard import AircraftWizard
from app.bot.texts.i18n import t
from app.database.models import StationTypeEnum, User
from app.domain.envelope import CGEnvelope, EnvelopeRow
from app.domain.exceptions import DomainError, InvalidEnvelopeError
from app.domain.models import StationType
from app.services.aircraft_service import (
    AircraftRevisionDraft,
    AircraftService,
    EnvelopeRowDraft,
    StationDraft,
    useful_load_warning,
)

router = Router(name="aircraft_wizard")

# Convenience default for 100LL avgas. It is never applied silently: the pilot confirms this
# value or enters another density while configuring a fuel station.
DEFAULT_FUEL_DENSITY_LB_PER_GAL = Decimal("6.0")


def _lang(user: User) -> str:
    return user.language or "en"


def _is_update(data: dict) -> bool:
    return bool(data.get("update_mode"))


def _show_skip(data: dict, key: str) -> bool:
    """Skip only makes sense when there's no current value to fall back on. Once a field is
    already set, "Keep current" is the only sensible way to leave it unchanged -- Skip would
    silently clear it, which sitting right next to "Keep current" invites by mistake."""
    return not (_is_update(data) and data.get(key) is not None)


def _show_keep(data: dict, key: str) -> bool:
    """Do not offer a meaningless Keep current button when no value is stored."""
    return _is_update(data) and data.get(key) is not None


def _current_suffix(data: dict, key: str, unit: str = "", lang: str = "en") -> str:
    """Shown only in update mode: reminds the pilot what's on file today, since typing a new
    value is how they edit a field -- Keep current/Skip are for leaving it untouched."""
    if not _is_update(data):
        return ""
    value = data.get(key)
    if value is None:
        return ""
    try:
        display = fmt(Decimal(value), unit)
    except (InvalidOperation, ValueError):
        display = f"{value}{unit}"
    return f"\n\n({t('current_value_hint', lang, value=display)})"


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
    await message.answer(
        t("ask_empty_weight", lang) + _current_suffix(data, "basic_empty_weight_lb", " lb", lang),
        reply_markup=keep_cancel_keyboard(lang, show_keep=_is_update(data)),
    )


async def render_cg_or_moment_choice(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    suffix = _current_suffix(data, "basic_empty_cg_in", " in", lang) or _current_suffix(
        data, "basic_empty_moment_lb_in", " lb-in", lang
    )
    await message.answer(t("ask_cg_or_moment", lang) + suffix, reply_markup=cg_or_moment_keyboard(lang, show_keep=_is_update(data)))


async def render_empty_cg(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_empty_cg", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


async def render_empty_moment(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_empty_moment", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))




async def render_max_ramp_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(
        t("ask_max_ramp_weight", lang) + _current_suffix(data, "max_ramp_weight_lb", " lb", lang),
        reply_markup=skip_cancel_keyboard(
            lang,
            show_keep=_show_keep(data, "max_ramp_weight_lb"),
            show_skip=_show_skip(data, "max_ramp_weight_lb"),
        ),
    )


async def render_max_takeoff_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(
        t("ask_max_takeoff_weight", lang) + _current_suffix(data, "max_takeoff_weight_lb", " lb", lang),
        reply_markup=keep_cancel_keyboard(lang, show_keep=_is_update(data)),
    )


async def render_max_landing_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(
        t("ask_max_landing_weight", lang) + _current_suffix(data, "max_landing_weight_lb", " lb", lang),
        reply_markup=skip_cancel_keyboard(
            lang,
            show_keep=_show_keep(data, "max_landing_weight_lb"),
            show_skip=_show_skip(data, "max_landing_weight_lb"),
        ),
    )


async def render_max_zfw(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(
        t("ask_max_zfw", lang) + _current_suffix(data, "max_zero_fuel_weight_lb", " lb", lang),
        reply_markup=skip_cancel_keyboard(
            lang,
            show_keep=_show_keep(data, "max_zero_fuel_weight_lb"),
            show_skip=_show_skip(data, "max_zero_fuel_weight_lb"),
        ),
    )


async def render_known_useful_load(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    await message.answer(
        t("ask_known_useful_load", lang) + _current_suffix(data, "known_useful_load_lb", " lb", lang),
        reply_markup=skip_cancel_keyboard(
            lang,
            show_keep=_show_keep(data, "known_useful_load_lb"),
            show_skip=_show_skip(data, "known_useful_load_lb"),
        ),
    )


async def render_station_add_prompt(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    stations = data.get("stations", [])
    rows = [
        [
            InlineKeyboardButton(text=t("btn_add_another_station", lang), callback_data="wizard:yes"),
            InlineKeyboardButton(text=t("btn_done_adding_stations", lang), callback_data="wizard:no"),
        ]
    ]
    if stations:
        rows.append(
            [InlineKeyboardButton(text=t("btn_edit_station", lang), callback_data="wizard:edit_prompt")]
        )
        rows.append(
            [InlineKeyboardButton(text=t("btn_remove_station", lang), callback_data="wizard:remove_prompt")]
        )
    text = t("ask_add_station", lang)
    if stations:
        text += f"\n\n{t('stations_added', lang)}\n" + "\n".join(
            f"- {s['name']}" for s in stations
        )
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def render_remove_station_prompt(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    stations = data.get("stations", [])
    rows = [
        [InlineKeyboardButton(text=f"🗑 {s['name']}", callback_data=f"wizard:remove_at:{i}")]
        for i, s in enumerate(stations)
    ]
    rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data="wizard:remove_cancel")])
    await message.answer(
        t("ask_remove_station", lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def render_edit_station_prompt(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    stations = data.get("stations", [])
    rows = [
        [InlineKeyboardButton(text=f"✏️ {s['name']}", callback_data=f"wizard:edit_at:{i}")]
        for i, s in enumerate(stations)
    ]
    rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data="wizard:edit_cancel")])
    await message.answer(
        t("ask_edit_station", lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def render_station_edit_arm(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    station = data["stations"][data["editing_station_index"]]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_keep", _lang(user)), callback_data="wizard:keep")],
            [
                InlineKeyboardButton(
                    text=t("btn_rename", _lang(user)), callback_data="wizard:edit_station_name"
                ),
                InlineKeyboardButton(
                    text=t("btn_change_type", _lang(user)), callback_data="wizard:edit_station_type"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_cancel", _lang(user)), callback_data="wizard:cancel"
                )
            ],
        ]
    )
    await message.answer(
        t(
            "ask_edit_station_arm",
            _lang(user),
            station=station["name"],
            current=fmt(Decimal(station["default_arm_in"])),
        ),
        reply_markup=keyboard,
    )


async def render_station_edit_name(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    station = data["stations"][data["editing_station_index"]]
    await message.answer(
        t("ask_edit_station_name", _lang(user), station=station["name"]),
        reply_markup=keep_cancel_keyboard(_lang(user), show_keep=True, show_back=False),
    )


async def render_station_edit_type(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    station = data["stations"][data["editing_station_index"]]
    station_type = StationTypeEnum(station["station_type"])
    await message.answer(
        t(
            "ask_edit_station_type",
            _lang(user),
            station=station["name"],
            current=t(STATION_TYPE_TEXT_KEYS[station_type], _lang(user)),
        ),
        reply_markup=station_type_keyboard(_lang(user), show_back=False, show_done=False),
    )


async def render_station_edit_fuel_volume(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    station = data["stations"][data["editing_station_index"]]
    current = station.get("maximum_volume_gal")
    current_text = fmt(Decimal(current), " gal") if current is not None else t("not_set", _lang(user))
    await message.answer(
        t(
            "ask_edit_fuel_volume",
            _lang(user),
            station=station["name"],
            current=current_text,
        ),
        reply_markup=keep_cancel_keyboard(
            _lang(user), show_keep=current is not None, show_back=False
        ),
    )


async def render_station_type(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    has_stations = bool(data.get("stations"))
    await message.answer(
        t("ask_station_type", lang), reply_markup=station_type_keyboard(lang, show_done=has_stations)
    )


def _default_station_name(
    station_type_value: str, stations: list[dict], lang: str = "en"
) -> str:
    station_type = StationTypeEnum(station_type_value)
    base = t(STATION_TYPE_TEXT_KEYS[station_type], lang)
    count = sum(1 for s in stations if s["station_type"] == station_type_value)
    return base if count == 0 else f"{base} {count + 1}"


async def render_station_name(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    default_name = _default_station_name(
        data["current_station_type"], data.get("stations", []), lang
    )
    await message.answer(
        f"{t('ask_station_name', lang)}\n{t('suggested_station_name', lang)}",
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


async def render_station_fuel_max_volume(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("ask_fuel_max_volume", _lang(user)), reply_markup=cancel_only_keyboard(_lang(user)))


async def render_station_max_weight(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(
        t("ask_station_max_weight", _lang(user)),
        reply_markup=skip_cancel_keyboard(_lang(user)),
    )


def _fuel_density_keyboard(lang: str, *, show_keep: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=t("btn_use_100ll_density", lang),
                callback_data="wizard:default_fuel_density",
            )
        ]
    ]
    if show_keep:
        rows.append([InlineKeyboardButton(text=t("btn_keep", lang), callback_data="wizard:keep")])
    rows.append([InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_station_fuel_density(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(
        t("ask_fuel_density", _lang(user)),
        reply_markup=_fuel_density_keyboard(_lang(user)),
    )


async def render_station_edit_max_weight(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    station = data["stations"][data["editing_station_index"]]
    current = station.get("maximum_weight_lb")
    current_text = fmt(Decimal(current), " lb") if current is not None else t("not_set", _lang(user))
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_keep", _lang(user)), callback_data="wizard:keep")],
            [InlineKeyboardButton(text=t("btn_clear_limit", _lang(user)), callback_data="wizard:clear")],
            [InlineKeyboardButton(text=t("btn_cancel", _lang(user)), callback_data="wizard:cancel")],
        ]
    )
    await message.answer(
        t(
            "ask_edit_station_max_weight",
            _lang(user),
            station=station["name"],
            current=current_text,
        ),
        reply_markup=keyboard,
    )


async def render_station_edit_fuel_density(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    station = data["stations"][data["editing_station_index"]]
    current = station.get("fuel_density_lb_per_gal")
    current_text = fmt(Decimal(current), " lb/gal") if current is not None else t("not_set", _lang(user))
    await message.answer(
        t(
            "ask_edit_fuel_density",
            _lang(user),
            station=station["name"],
            current=current_text,
        ),
        reply_markup=_fuel_density_keyboard(_lang(user), show_keep=current is not None),
    )


def _envelope_row_label(r: dict) -> str:
    return (
        f"{fmt(Decimal(r['weight_lb']), ' lb')}: "
        f"{fmt(Decimal(r['forward_cg_limit_in']))}-{fmt(Decimal(r['aft_cg_limit_in']), ' in')}"
    )


async def render_envelope_rows(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    rows = data.get("envelope_rows", [])
    text = t("envelope_prompt", lang)
    if rows:
        text += f"\n\n{t('envelope_rows_added', lang)}\n" + "\n".join(
            f"- {_envelope_row_label(r)}" for r in rows
        )
    await message.answer(text, reply_markup=envelope_keyboard(lang, has_rows=bool(rows)))


async def render_remove_envelope_row_prompt(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    rows = data.get("envelope_rows", [])
    keyboard_rows = [
        [InlineKeyboardButton(text=f"🗑 {_envelope_row_label(r)}", callback_data=f"wizard:remove_row_at:{i}")]
        for i, r in enumerate(rows)
    ]
    keyboard_rows.append(
        [InlineKeyboardButton(text=t("btn_back", lang), callback_data="wizard:remove_row_cancel")]
    )
    await message.answer(
        t("ask_remove_envelope_row", lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
    )


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
    AircraftWizard.review.state: render_review,
}


async def _cannot_go_back(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("already_first_step", _lang(user)))


@router.callback_query(StateFilter(AircraftWizard), F.data == "wizard:back")
async def wizard_back(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await go_back(callback.message, state, user, RENDERERS, _cannot_go_back)
    await callback.answer()


# ---------------------------------------------------------------------------
# Entry point + top-level cancel
# ---------------------------------------------------------------------------


def _setup_mode_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_quick_setup", lang), callback_data="wizard:quick_setup")],
            [InlineKeyboardButton(text=t("btn_advanced_setup", lang), callback_data="wizard:advanced_setup")],
        ]
    )


@router.message(F.text.in_({t("menu_add_aircraft", "en"), t("menu_add_aircraft", "ru")}))
async def start_wizard(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    await state.clear()
    await state.update_data(stations=[], envelope_rows=[])
    await message.answer(t("setup_started", lang), reply_markup=ReplyKeyboardRemove())
    await message.answer(
        t("setup_intro", lang),
        reply_markup=_setup_mode_keyboard(lang),
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
    await message.answer(
        t("rental_setup_started", _lang(user)), reply_markup=ReplyKeyboardRemove()
    )
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


@router.message(AircraftWizard.tail_number, F.text)
async def got_tail_number(message: Message, state: FSMContext, user: User) -> None:
    tail_number = message.text.strip().upper()
    if not tail_number:
        await message.answer(t("error_generic", _lang(user), detail="tail number required"))
        return
    if len(tail_number) > 16:
        await message.answer(
            t("error_generic", _lang(user), detail="tail number must be 16 characters or fewer")
        )
        return
    await state.update_data(tail_number=tail_number)
    data = await state.get_data()
    if _is_quick(data):
        await state.update_data(nickname=None, manufacturer=None)
        await goto(message, state, user, AircraftWizard.model, render_model)
    else:
        await goto(message, state, user, AircraftWizard.nickname, render_nickname)


@router.message(AircraftWizard.nickname, F.text)
async def got_nickname(message: Message, state: FSMContext, user: User) -> None:
    nickname = parse_optional_text(message.text)
    if nickname is not None and len(nickname) > 64:
        await message.answer(
            t("error_generic", _lang(user), detail="nickname must be 64 characters or fewer")
        )
        return
    await state.update_data(nickname=nickname)
    await goto(message, state, user, AircraftWizard.manufacturer, render_manufacturer)


@router.callback_query(AircraftWizard.nickname, F.data == "wizard:skip")
async def skip_nickname(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(nickname=None)
    await goto(callback.message, state, user, AircraftWizard.manufacturer, render_manufacturer)
    await callback.answer()


@router.message(AircraftWizard.manufacturer, F.text)
async def got_manufacturer(message: Message, state: FSMContext, user: User) -> None:
    manufacturer = parse_optional_text(message.text)
    if manufacturer is not None and len(manufacturer) > 64:
        await message.answer(
            t("error_generic", _lang(user), detail="manufacturer must be 64 characters or fewer")
        )
        return
    await state.update_data(manufacturer=manufacturer)
    await goto(message, state, user, AircraftWizard.model, render_model)


@router.callback_query(AircraftWizard.manufacturer, F.data == "wizard:skip")
async def skip_manufacturer(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(manufacturer=None)
    await goto(callback.message, state, user, AircraftWizard.model, render_model)
    await callback.answer()


@router.message(AircraftWizard.model, F.text)
async def got_model(message: Message, state: FSMContext, user: User) -> None:
    model = message.text.strip()
    if not model:
        await message.answer(t("error_generic", _lang(user), detail="model required"))
        return
    if len(model) > 64:
        await message.answer(
            t("error_generic", _lang(user), detail="model must be 64 characters or fewer")
        )
        return
    await state.update_data(model=model)
    await goto(message, state, user, AircraftWizard.empty_weight, render_empty_weight)


# ---------------------------------------------------------------------------
# Empty weight / CG / moment
# ---------------------------------------------------------------------------


@router.message(AircraftWizard.empty_weight, F.text)
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


async def _advance_past_empty_record(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    if _is_quick(data):
        await state.update_data(
            max_ramp_weight_lb=None,
            max_landing_weight_lb=None,
            max_zero_fuel_weight_lb=None,
            known_useful_load_lb=None,
        )
        await goto(message, state, user, AircraftWizard.max_takeoff_weight, render_max_takeoff_weight)
    else:
        await goto(message, state, user, AircraftWizard.max_ramp_weight, render_max_ramp_weight)


@router.callback_query(AircraftWizard.cg_or_moment_choice, F.data == "wizard:keep_cg_moment")
async def keep_cg_moment(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await _advance_past_empty_record(callback.message, state, user)
    await callback.answer()


@router.message(AircraftWizard.empty_cg, F.text)
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
    await _advance_past_empty_record(message, state, user)


@router.message(AircraftWizard.empty_moment, F.text)
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
    await _advance_past_empty_record(message, state, user)


# ---------------------------------------------------------------------------
# Scalar weight limits + useful load
# ---------------------------------------------------------------------------


@router.message(AircraftWizard.max_ramp_weight, F.text)
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


@router.message(AircraftWizard.max_takeoff_weight, F.text)
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


@router.message(AircraftWizard.max_landing_weight, F.text)
async def got_max_landing_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_optional_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(max_landing_weight_lb=str(value) if value is not None else None)
    await _advance_past_max_landing(message, state, user)


@router.callback_query(AircraftWizard.max_landing_weight, F.data == "wizard:skip")
async def skip_max_landing_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(max_landing_weight_lb=None)
    await _advance_past_max_landing(callback.message, state, user)
    await callback.answer()


@router.callback_query(AircraftWizard.max_landing_weight, F.data == "wizard:keep")
async def keep_max_landing_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await _advance_past_max_landing(callback.message, state, user)
    await callback.answer()


async def _advance_past_max_landing(
    message: Message, state: FSMContext, user: User
) -> None:
    data = await state.get_data()
    # Updating a typical light-GA profile should not stop on an unset structural limit.
    # Preserve and expose an existing MZFW, while new Advanced Setup still offers the field.
    if _is_update(data) and data.get("max_zero_fuel_weight_lb") is None:
        await goto(
            message,
            state,
            user,
            AircraftWizard.known_useful_load,
            render_known_useful_load,
        )
        return
    await goto(message, state, user, AircraftWizard.max_zfw, render_max_zfw)


@router.message(AircraftWizard.max_zfw, F.text)
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


@router.message(AircraftWizard.known_useful_load, F.text)
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


@router.callback_query(AircraftWizard.station_add_prompt, F.data == "wizard:remove_prompt")
async def remove_station_prompt(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await render_remove_station_prompt(callback.message, state, user)


@router.callback_query(AircraftWizard.station_add_prompt, F.data == "wizard:remove_cancel")
async def remove_station_cancel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await render_station_add_prompt(callback.message, state, user)


@router.callback_query(AircraftWizard.station_add_prompt, F.data.startswith("wizard:remove_at:"))
async def remove_station_at(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    index = int(callback.data.split(":")[-1])
    data = await state.get_data()
    stations = data.get("stations", [])
    if 0 <= index < len(stations):
        removed = stations.pop(index)
        await state.update_data(stations=stations)
        await callback.answer(t("station_removed", _lang(user), station=removed["name"]))
    else:
        await callback.answer()
    await render_station_add_prompt(callback.message, state, user)


@router.callback_query(AircraftWizard.station_add_prompt, F.data == "wizard:edit_prompt")
async def edit_station_prompt(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await render_edit_station_prompt(callback.message, state, user)


@router.callback_query(AircraftWizard.station_add_prompt, F.data == "wizard:edit_cancel")
async def edit_station_cancel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await render_station_add_prompt(callback.message, state, user)


@router.callback_query(AircraftWizard.station_add_prompt, F.data.startswith("wizard:edit_at:"))
async def edit_station_at(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    index = int(callback.data.split(":")[-1])
    data = await state.get_data()
    stations = data.get("stations", [])
    if not (0 <= index < len(stations)):
        await callback.answer()
        return
    await state.update_data(editing_station_index=index)
    await callback.answer()
    await state.set_state(AircraftWizard.station_edit_arm)
    await render_station_edit_arm(callback.message, state, user)


@router.callback_query(
    AircraftWizard.station_edit_arm, F.data == "wizard:edit_station_name"
)
async def edit_station_name_prompt(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    await callback.answer()
    await state.set_state(AircraftWizard.station_edit_name)
    await render_station_edit_name(callback.message, state, user)


@router.message(AircraftWizard.station_edit_name, F.text)
async def got_station_edit_name(message: Message, state: FSMContext, user: User) -> None:
    name = message.text.strip()
    if not name:
        await message.answer(t("error_generic", _lang(user), detail="name required"))
        return
    if len(name) > 64:
        await message.answer(
            t("error_generic", _lang(user), detail="station name must be 64 characters or fewer")
        )
        return

    data = await state.get_data()
    stations = data["stations"]
    station = stations[data["editing_station_index"]]
    words = {word.strip("-_/()[]") for word in name.casefold().split()}
    if station["station_type"] != StationType.FUEL.value and (
        "fuel" in words or "tank" in words or "tanks" in words
    ):
        await message.answer(t("fuel_like_name_edit_error", _lang(user)))
        return

    station["name"] = name
    await state.update_data(stations=stations)
    await state.set_state(AircraftWizard.station_edit_arm)
    await message.answer(t("station_name_updated", _lang(user)))
    await render_station_edit_arm(message, state, user)


@router.callback_query(AircraftWizard.station_edit_name, F.data == "wizard:keep")
async def keep_station_edit_name(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    await callback.answer()
    await state.set_state(AircraftWizard.station_edit_arm)
    await render_station_edit_arm(callback.message, state, user)


@router.callback_query(
    AircraftWizard.station_edit_arm, F.data == "wizard:edit_station_type"
)
async def edit_station_type_prompt(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    await callback.answer()
    await state.set_state(AircraftWizard.station_edit_type)
    await render_station_edit_type(callback.message, state, user)


def _apply_station_type_change(station: dict, new_type: str) -> None:
    """Change type without retaining fields whose units/meaning no longer match.

    In particular, converting the historical failure case CUSTOM -> FUEL must clear a pound
    limit and force the pilot to enter usable gallons and fuel density. Converting away from
    FUEL must never leave gallon/density metadata attached to a non-fuel load station.
    """
    if station.get("station_type") == new_type:
        return
    station["station_type"] = new_type
    if new_type == StationType.FUEL.value:
        station["maximum_weight_lb"] = None
        station["maximum_volume_gal"] = None
        station["fuel_density_lb_per_gal"] = None
        station["is_adjustable_arm"] = False
        station["minimum_arm_in"] = None
        station["maximum_arm_in"] = None
        return

    station["maximum_volume_gal"] = None
    station["fuel_density_lb_per_gal"] = None
    if new_type not in {StationType.BAGGAGE.value, StationType.CUSTOM.value}:
        station["maximum_weight_lb"] = None
    if new_type != StationType.CUSTOM.value:
        station["is_adjustable_arm"] = False
        station["minimum_arm_in"] = None
        station["maximum_arm_in"] = None


@router.callback_query(
    AircraftWizard.station_edit_type, F.data.startswith("stype:")
)
async def got_station_edit_type(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    new_type = callback.data.split(":", 1)[1]
    data = await state.get_data()
    stations = data["stations"]
    station = stations[data["editing_station_index"]]
    _apply_station_type_change(station, new_type)
    await state.update_data(stations=stations)
    await callback.answer(t("station_type_updated", _lang(user)))
    await state.set_state(AircraftWizard.station_edit_arm)
    await render_station_edit_arm(callback.message, state, user)


async def _finish_station_edit(message: Message, state: FSMContext, user: User) -> None:
    """Return to the station hub in the correct FSM state.

    The old implementation only rendered the hub while leaving the FSM in an edit state. The
    subsequent "Done adding stations" callback therefore had no matching handler and appeared
    to break/save nothing. Always change state before rendering the hub.
    """
    await state.update_data(editing_station_index=None)
    await state.set_state(AircraftWizard.station_add_prompt)
    await message.answer(t("station_updated", _lang(user)))
    await render_station_add_prompt(message, state, user)


async def _advance_past_station_edit_arm(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    station = data["stations"][data["editing_station_index"]]
    station_type = station["station_type"]
    if station_type == StationType.FUEL.value:
        await state.set_state(AircraftWizard.station_edit_fuel_volume)
        await render_station_edit_fuel_volume(message, state, user)
    elif station_type in {StationType.BAGGAGE.value, StationType.CUSTOM.value}:
        await state.set_state(AircraftWizard.station_edit_max_weight)
        await render_station_edit_max_weight(message, state, user)
    else:
        await _finish_station_edit(message, state, user)


@router.message(AircraftWizard.station_edit_arm, F.text)
async def got_station_edit_arm(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text, allow_negative=True)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    stations = data["stations"]
    station = stations[data["editing_station_index"]]
    if station.get("is_adjustable_arm"):
        minimum = Decimal(station["minimum_arm_in"])
        maximum = Decimal(station["maximum_arm_in"])
        if not minimum <= value <= maximum:
            await message.answer(
                t(
                    "error_generic",
                    lang,
                    detail=f"ARM must be inside the configured range {minimum}-{maximum}",
                )
            )
            return
    station["default_arm_in"] = str(value)
    await state.update_data(stations=stations)
    await _advance_past_station_edit_arm(message, state, user)


@router.callback_query(AircraftWizard.station_edit_arm, F.data == "wizard:keep")
async def keep_station_edit_arm(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _advance_past_station_edit_arm(callback.message, state, user)


@router.message(AircraftWizard.station_edit_max_weight, F.text)
async def got_station_edit_max_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text)
        if value <= 0:
            raise InputParseError("must be positive")
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    stations = data["stations"]
    stations[data["editing_station_index"]]["maximum_weight_lb"] = str(value)
    await state.update_data(stations=stations)
    await _finish_station_edit(message, state, user)


@router.callback_query(AircraftWizard.station_edit_max_weight, F.data == "wizard:keep")
async def keep_station_edit_max_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _finish_station_edit(callback.message, state, user)


@router.callback_query(AircraftWizard.station_edit_max_weight, F.data == "wizard:clear")
async def clear_station_edit_max_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    stations = data["stations"]
    stations[data["editing_station_index"]]["maximum_weight_lb"] = None
    await state.update_data(stations=stations)
    await callback.answer()
    await _finish_station_edit(callback.message, state, user)


async def _advance_to_station_edit_fuel_density(
    message: Message, state: FSMContext, user: User
) -> None:
    await state.set_state(AircraftWizard.station_edit_fuel_density)
    await render_station_edit_fuel_density(message, state, user)


@router.message(AircraftWizard.station_edit_fuel_volume, F.text)
async def got_station_edit_fuel_volume(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text)
        if value <= 0:
            raise InputParseError("must be positive")
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    stations = data["stations"]
    stations[data["editing_station_index"]]["maximum_volume_gal"] = str(value)
    await state.update_data(stations=stations)
    await _advance_to_station_edit_fuel_density(message, state, user)


@router.callback_query(AircraftWizard.station_edit_fuel_volume, F.data == "wizard:keep")
async def keep_station_edit_fuel_volume(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _advance_to_station_edit_fuel_density(callback.message, state, user)


async def _save_station_edit_fuel_density(
    message: Message, state: FSMContext, user: User, value: Decimal
) -> None:
    data = await state.get_data()
    stations = data["stations"]
    stations[data["editing_station_index"]]["fuel_density_lb_per_gal"] = str(value)
    await state.update_data(stations=stations)
    await _finish_station_edit(message, state, user)


@router.message(AircraftWizard.station_edit_fuel_density, F.text)
async def got_station_edit_fuel_density(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text)
        if value <= 0:
            raise InputParseError("must be positive")
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await _save_station_edit_fuel_density(message, state, user, value)


@router.callback_query(AircraftWizard.station_edit_fuel_density, F.data == "wizard:keep")
async def keep_station_edit_fuel_density(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _finish_station_edit(callback.message, state, user)


@router.callback_query(
    AircraftWizard.station_edit_fuel_density, F.data == "wizard:default_fuel_density"
)
async def default_station_edit_fuel_density(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    await callback.answer()
    await _save_station_edit_fuel_density(
        callback.message, state, user, DEFAULT_FUEL_DENSITY_LB_PER_GAL
    )


@router.callback_query(AircraftWizard.station_add_prompt, F.data == "wizard:no")
async def stations_done(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await goto(callback.message, state, user, AircraftWizard.envelope_rows, render_envelope_rows)
    await callback.answer()


@router.callback_query(AircraftWizard.station_type, F.data == "wizard:done_stations")
async def done_stations_from_type_screen(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    """Escape hatch for pilots who land on the station-type picker (e.g. after tapping "Yes" by
    habit) but actually have nothing more to add -- lets them finish without backing out to the
    Add a station? prompt first."""
    await goto(callback.message, state, user, AircraftWizard.envelope_rows, render_envelope_rows)
    await callback.answer()


@router.callback_query(AircraftWizard.station_type, F.data.startswith("stype:"))
async def got_station_type(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    station_type = callback.data.split(":", 1)[1]
    await state.update_data(current_station_type=station_type)
    await goto(callback.message, state, user, AircraftWizard.station_name, render_station_name)
    await callback.answer()


@router.message(AircraftWizard.station_name, F.text)
async def got_station_name(message: Message, state: FSMContext, user: User) -> None:
    name = message.text.strip()
    if not name:
        await message.answer(t("error_generic", _lang(user), detail="name required"))
        return
    if len(name) > 64:
        await message.answer(
            t("error_generic", _lang(user), detail="station name must be 64 characters or fewer")
        )
        return
    data = await state.get_data()
    words = {word.strip("-_/()[]") for word in name.casefold().split()}
    if data.get("current_station_type") != StationType.FUEL.value and (
        "fuel" in words or "tank" in words or "tanks" in words
    ):
        await message.answer(t("fuel_like_name_new_error", _lang(user)))
        return
    await state.update_data(current_station_name=name)
    await goto(message, state, user, AircraftWizard.station_arm, render_station_arm)


@router.callback_query(AircraftWizard.station_name, F.data == "wizard:use_default_name")
async def use_default_station_name(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    default_name = _default_station_name(
        data["current_station_type"], data.get("stations", []), _lang(user)
    )
    await state.update_data(current_station_name=default_name)
    await goto(callback.message, state, user, AircraftWizard.station_arm, render_station_arm)
    await callback.answer()


# Only custom stations are ever asked whether their ARM is adjustable -- seats, baggage
# compartments, and fuel tanks are physically fixed locations in the airframe.
_ADJUSTABLE_ARM_ELIGIBLE = {StationType.CUSTOM.value}


@router.message(AircraftWizard.station_arm, F.text)
async def got_station_arm(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        arm = parse_decimal(message.text, allow_negative=True)
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
    station_type = data["current_station_type"]
    if station_type == StationType.FUEL.value:
        await goto(
            message,
            state,
            user,
            AircraftWizard.station_fuel_max_volume,
            render_station_fuel_max_volume,
        )
    elif station_type in {StationType.BAGGAGE.value, StationType.CUSTOM.value}:
        # A known compartment/station limit is necessary before the recommendation engine may
        # ever suggest adding load there. It remains optional because not every station has an
        # independent published structural limit.
        await goto(
            message, state, user, AircraftWizard.station_max_weight, render_station_max_weight
        )
    else:
        await _finalize_station(message, state, user, max_weight=None)


@router.callback_query(AircraftWizard.station_arm_mode, F.data == "wizard:arm_fixed")
async def arm_fixed(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(
        current_station_adjustable=False,
        current_station_min_arm=None,
        current_station_max_arm=None,
    )
    await callback.answer()
    await _after_arm_configured(callback.message, state, user)


@router.callback_query(AircraftWizard.station_arm_mode, F.data == "wizard:arm_adjustable")
async def arm_adjustable(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(current_station_adjustable=True)
    await goto(
        callback.message, state, user, AircraftWizard.station_min_arm, render_station_min_arm
    )
    await callback.answer()


@router.message(AircraftWizard.station_min_arm, F.text)
async def got_station_min_arm(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text, allow_negative=True)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await state.update_data(current_station_min_arm=str(value))
    await goto(message, state, user, AircraftWizard.station_max_arm, render_station_max_arm)


@router.message(AircraftWizard.station_max_arm, F.text)
async def got_station_max_arm(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text, allow_negative=True)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    min_arm = Decimal(data["current_station_min_arm"])
    if value < min_arm:
        await message.answer(t("error_generic", lang, detail="max ARM must be >= min ARM"))
        return
    default_arm = Decimal(data["current_station_arm"])
    if not min_arm <= default_arm <= value:
        await message.answer(
            t("error_generic", lang, detail="default ARM must be inside the min/max range")
        )
        return
    await state.update_data(current_station_max_arm=str(value))
    await _after_arm_configured(message, state, user)


@router.message(AircraftWizard.station_max_weight, F.text)
async def got_station_max_weight(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text)
        if value <= 0:
            raise InputParseError("must be positive")
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await _finalize_station(message, state, user, max_weight=value)


@router.callback_query(AircraftWizard.station_max_weight, F.data == "wizard:skip")
async def skip_station_max_weight(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _finalize_station(callback.message, state, user, max_weight=None)


@router.message(AircraftWizard.station_fuel_max_volume, F.text)
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
    await goto(
        message, state, user, AircraftWizard.station_fuel_density, render_station_fuel_density
    )


async def _finish_new_fuel_station(
    message: Message, state: FSMContext, user: User, density: Decimal
) -> None:
    data = await state.get_data()
    await _finalize_station(
        message,
        state,
        user,
        max_weight=None,
        fuel_max_volume=Decimal(data["current_station_fuel_max_volume"]),
        fuel_density=density,
    )


@router.message(AircraftWizard.station_fuel_density, F.text)
async def got_fuel_density(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        value = parse_decimal(message.text)
        if value <= 0:
            raise InputParseError("must be positive")
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await _finish_new_fuel_station(message, state, user, value)


@router.callback_query(
    AircraftWizard.station_fuel_density, F.data == "wizard:default_fuel_density"
)
async def default_fuel_density(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _finish_new_fuel_station(
        callback.message, state, user, DEFAULT_FUEL_DENSITY_LB_PER_GAL
    )


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
        current_station_fuel_density=None,
    )
    # Fresh hub screen (not goto/history -- the station is now committed, so Back should not
    # be able to re-open a finalized station's fields and re-append a duplicate).
    await state.set_state(AircraftWizard.station_add_prompt)
    await message.answer(t("station_added", _lang(user), station=station["name"]))
    await render_station_add_prompt(message, state, user)


# ---------------------------------------------------------------------------
# CG envelope
# ---------------------------------------------------------------------------


@router.message(AircraftWizard.envelope_rows, F.text)
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


@router.callback_query(AircraftWizard.envelope_rows, F.data == "wizard:remove_row_prompt")
async def remove_row_prompt(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await render_remove_envelope_row_prompt(callback.message, state, user)


@router.callback_query(AircraftWizard.envelope_rows, F.data == "wizard:remove_row_cancel")
async def remove_row_cancel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await render_envelope_rows(callback.message, state, user)


@router.callback_query(AircraftWizard.envelope_rows, F.data.startswith("wizard:remove_row_at:"))
async def remove_row_at(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    index = int(callback.data.split(":")[-1])
    data = await state.get_data()
    rows = data.get("envelope_rows", [])
    if 0 <= index < len(rows):
        rows.pop(index)
        await state.update_data(envelope_rows=rows)
        await callback.answer(t("row_removed", _lang(user)))
    else:
        await callback.answer()
    await render_envelope_rows(callback.message, state, user)


@router.callback_query(AircraftWizard.envelope_rows, F.data == "wizard:skip_envelope")
async def skip_envelope(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(envelope_rows=[])
    await callback.answer()
    await callback.message.answer(t("envelope_skipped", _lang(user)))
    await _advance_past_envelope(callback.message, state, user)


async def _advance_past_envelope(message: Message, state: FSMContext, user: User) -> None:
    # Source document name/date were dropped as a wizard question -- the aircraft is already
    # identified by its tail number, and pilots found tracking a separate "source document"
    # pointless. The fields remain supported in the data model; they're just never asked for.
    # In update mode, whatever value the aircraft already has stays untouched (pre-loaded by
    # aircraft_update.py); for a brand-new aircraft the keys are simply absent, so review/save
    # naturally treats them as not set.
    await goto(message, state, user, AircraftWizard.review, render_review)


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


def _summary_fmt(value: str | Decimal, unit: str = "") -> str:
    """Phone-friendly numeric formatting with grouping and at most one decimal place."""
    quantized = Decimal(value).quantize(Decimal("0.1"))
    text = f"{quantized:,.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text}{unit}"


def _summary_arm(station: dict, lang: str) -> str:
    default = _summary_fmt(station["default_arm_in"], " in")
    if not station.get("is_adjustable_arm"):
        return t("profile_arm_fixed", lang, value=default)
    minimum = _summary_fmt(station["minimum_arm_in"], " in")
    maximum = _summary_fmt(station["maximum_arm_in"], " in")
    return t(
        "profile_arm_adjustable",
        lang,
        minimum=minimum,
        maximum=maximum,
        default=default,
    )


def render_summary(data: dict, lang: str) -> str:
    lines = [t("review_aircraft_summary", lang), ""]

    identity = str(data.get("tail_number") or "—")
    if data.get("model"):
        identity += f" — {data['model']}"
    lines.append(identity)
    if data.get("nickname"):
        lines.append(t("profile_nickname", lang, value=data["nickname"]))
    if data.get("manufacturer"):
        lines.append(t("profile_manufacturer", lang, value=data["manufacturer"]))

    lines.extend(
        [
            "",
            t("profile_empty_aircraft", lang),
            t(
                "profile_empty_weight",
                lang,
                value=_summary_fmt(data["basic_empty_weight_lb"], " lb"),
            ),
            t(
                "profile_empty_cg",
                lang,
                value=_summary_fmt(data["basic_empty_cg_in"], " in"),
            ),
            t(
                "profile_empty_moment",
                lang,
                value=_summary_fmt(data["basic_empty_moment_lb_in"], " lb-in"),
            ),
            "",
            t("profile_weight_limits", lang),
        ]
    )
    if data.get("max_ramp_weight_lb"):
        lines.append(
            t(
                "profile_limit_ramp",
                lang,
                value=_summary_fmt(data["max_ramp_weight_lb"], " lb"),
            )
        )
    lines.append(
        t(
            "profile_limit_takeoff",
            lang,
            value=_summary_fmt(data["max_takeoff_weight_lb"], " lb"),
        )
    )
    if data.get("max_landing_weight_lb"):
        lines.append(
            t(
                "profile_limit_landing",
                lang,
                value=_summary_fmt(data["max_landing_weight_lb"], " lb"),
            )
        )
    if data.get("max_zero_fuel_weight_lb"):
        lines.append(
            t(
                "profile_limit_mzfw",
                lang,
                value=_summary_fmt(data["max_zero_fuel_weight_lb"], " lb"),
            )
        )

    stations = data.get("stations", [])
    fuel_stations = [
        station
        for station in stations
        if station.get("station_type") == StationType.FUEL.value
    ]
    load_stations = [station for station in stations if station not in fuel_stations]
    station_order = {
        StationType.FRONT_SEATS.value: 0,
        StationType.REAR_SEATS.value: 1,
        StationType.PASSENGER.value: 2,
        StationType.BAGGAGE.value: 3,
        StationType.CUSTOM.value: 4,
    }
    load_stations = sorted(
        enumerate(load_stations),
        key=lambda item: (station_order.get(item[1].get("station_type"), 99), item[0]),
    )

    if load_stations:
        lines.extend(["", t("profile_load_stations", lang, count=len(load_stations))])
        for _, station in load_stations:
            lines.append(f"• {station['name']} — {_summary_arm(station, lang)}")
            if station.get("maximum_weight_lb") is not None:
                lines.append(
                    "  "
                    + t(
                        "profile_station_max_load",
                        lang,
                        value=_summary_fmt(station["maximum_weight_lb"], " lb"),
                    )
                )

    if fuel_stations:
        lines.extend(["", t("profile_fuel_tanks", lang, count=len(fuel_stations))])
        for station in fuel_stations:
            lines.append(f"• {station['name']} — {_summary_arm(station, lang)}")
            fuel_details = []
            if station.get("maximum_volume_gal") is not None:
                fuel_details.append(
                    t(
                        "profile_tank_usable",
                        lang,
                        value=_summary_fmt(station["maximum_volume_gal"], " gal"),
                    )
                )
            if station.get("fuel_density_lb_per_gal") is not None:
                fuel_details.append(
                    t(
                        "profile_tank_density",
                        lang,
                        value=_summary_fmt(
                            station["fuel_density_lb_per_gal"], " lb/gal"
                        ),
                    )
                )
            if fuel_details:
                lines.append("  " + " • ".join(fuel_details))

    envelope_rows = data.get("envelope_rows", [])
    lines.append("")
    if envelope_rows:
        lines.append(t("profile_cg_envelope", lang, count=len(envelope_rows)))
        for row in envelope_rows:
            lines.append(
                f"• {_summary_fmt(row['weight_lb'], ' lb')} — "
                f"{_summary_fmt(row['forward_cg_limit_in'])}–"
                f"{_summary_fmt(row['aft_cg_limit_in'], ' in')}"
            )
    else:
        lines.append(t("profile_cg_envelope_missing", lang))
    return "\n".join(lines)


@router.callback_query(AircraftWizard.review, F.data == "wizard:confirm")
async def review_confirm(
    callback: CallbackQuery, state: FSMContext, user: User, aircraft_service: AircraftService
) -> None:
    lang = _lang(user)
    data = await state.get_data()
    try:
        draft = build_draft_from_state_data(data)

        if data.get("update_mode"):
            aircraft = await aircraft_service.get_aircraft(user.id, data["aircraft_id"])
            if aircraft is None:
                await callback.answer(t("aircraft_not_found", lang), show_alert=True)
                await state.clear()
                return
            await aircraft_service.update_aircraft(aircraft, draft)
        else:
            await aircraft_service.create_aircraft(
                user.id,
                data["tail_number"],
                data["model"],
                data.get("nickname"),
                data.get("manufacturer"),
                draft,
                is_temporary=bool(data.get("is_temporary")),
            )
    except (DomainError, InvalidOperation, KeyError, ValueError) as exc:
        # Validation happens before any database write. Keep the wizard open so the pilot can
        # go back and correct the profile instead of failing silently or saving a partial row.
        await callback.answer(str(exc), show_alert=True)
        return

    await state.clear()
    message_key = "revision_saved" if data.get("update_mode") else "aircraft_saved"
    await callback.message.answer(t(message_key, lang), reply_markup=main_menu_keyboard(lang))
    await callback.answer()


@router.message(StateFilter(AircraftWizard))
async def unsupported_aircraft_wizard_message(message: Message, user: User) -> None:
    await message.answer(t("unsupported_wizard_message", _lang(user)))
