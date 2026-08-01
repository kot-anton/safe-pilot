"""The standard under-a-minute calculation flow.

A configured aircraft asks only for combined front-seat weight, combined rear-seat weight,
combined baggage weight, and total usable fuel. Tank-distribution uncertainty is handled by the
pure domain engine; this handler never invents an exact split or performs Weight & Balance math.
"""
from __future__ import annotations

import json
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
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
    compact_decimal,
    fmt,
    parse_decimal,
    recommendation_text,
    short_tank_label,
)
from app.bot.handlers._common import lang as _lang
from app.bot.handlers._common import load_profile_and_aircraft as _load_profile_and_aircraft
from app.bot.handlers.wizard_nav import goto, go_back, has_history
from app.bot.keyboards.common import aircraft_list_keyboard, main_menu_keyboard
from app.bot.states.quick_calc_wizard import QuickCalcWizard
from app.bot.texts.i18n import t
from app.database.models import User
from app.domain.envelope import LimitStatus
from app.domain.exceptions import DomainError
from app.domain.fuel_allocation import FuelRangeStatus
from app.domain.models import StationType
from app.domain.quick_calculation import (
    QuickCalculationResult,
    quick_station_for_type,
    run_quick_calculation,
    validate_quick_profile,
)
from app.services.aircraft_service import AircraftService, suspicious_non_fuel_stations
from app.services.flight_service import FlightService

router = Router(name="quick_calculate")


async def _last_quick_input(
    user_id: int, aircraft_id: int, flight_service: FlightService
) -> dict | None:
    history = await flight_service.list_history(user_id, aircraft_id, limit=5)
    for calculation in history:
        if not str(
            getattr(calculation, "calculation_engine_version", "")
        ).endswith("-quick"):
            continue
        try:
            snapshot = json.loads(calculation.input_snapshot_json)
        except (ValueError, TypeError):
            continue
        if not isinstance(snapshot, dict):
            continue
        values = {}
        for key in ("front_lb", "rear_lb", "baggage_lb"):
            try:
                value = Decimal(str(snapshot.get(key)))
            except (ArithmeticError, TypeError, ValueError):
                continue
            if value.is_finite() and value >= 0:
                values[key] = compact_decimal(value)
        if values:
            return values
    return None


def _step_keyboard(
    lang: str,
    *,
    last_value: str | None,
    unit: str,
    show_zero: bool = True,
    show_back: bool = False,
) -> InlineKeyboardMarkup:
    rows = []
    if last_value is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(
                        "btn_use_last",
                        lang,
                        value=compact_decimal(last_value),
                        unit=unit,
                    ),
                    callback_data="quick:use_last",
                )
            ]
        )
    if show_zero:
        rows.append(
            [InlineKeyboardButton(text=t("btn_zero_load", lang), callback_data="quick:zero")]
        )
    footer = []
    if show_back:
        footer.append(
            InlineKeyboardButton(text=t("btn_back", lang), callback_data="quick:back")
        )
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="quick:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fuel_keyboard(
    lang: str, *, full_gal: Decimal, show_back: bool = False
) -> InlineKeyboardMarkup:
    # No "no fuel" shortcut: can't take off with zero fuel on board.
    rows = [
        [
            InlineKeyboardButton(
                text=t("btn_full_fuel", lang, value=fmt(full_gal, " gal")),
                callback_data="quick:full",
            )
        ],
    ]
    footer = []
    if show_back:
        footer.append(
            InlineKeyboardButton(text=t("btn_back", lang), callback_data="quick:back")
        )
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="quick:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _advanced_only_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_advanced_landing", lang), callback_data="quick:advanced"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_cancel", lang), callback_data="quick:cancel"
                )
            ],
        ]
    )


def calculation_mode_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_quick_takeoff", lang), callback_data="calc:quick"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_takeoff_landing", lang), callback_data="calc:advanced"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_cancel", lang), callback_data="quick:cancel"
                )
            ],
        ]
    )


def _result_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_change_load", lang), callback_data="quick:edit")],
            [
                InlineKeyboardButton(
                    text=t("btn_advanced_landing", lang), callback_data="quick:advanced"
                )
            ],
            [InlineKeyboardButton(text=t("btn_main_menu", lang), callback_data="quick:main_menu")],
        ]
    )


@router.message(Command("calculate"))
@router.message(F.text == t("menu_new_calc"))
async def show_calculation_options(
    message: Message,
    state: FSMContext,
    user: User,
) -> None:
    await state.clear()
    lang = _lang(user)
    await message.answer(
        t("choose_calculation_mode", lang),
        reply_markup=calculation_mode_keyboard(lang),
    )


@router.callback_query(F.data == "calc:quick")
async def calculation_mode_quick(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    await callback.answer()
    await start_quick_calculation(
        callback.message, state, user, aircraft_service, flight_service
    )


@router.callback_query(F.data == "calc:advanced")
async def calculation_mode_advanced(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    from app.bot.handlers.flight_calculation import start_calculation

    await callback.answer()
    await start_calculation(
        callback.message, state, user, aircraft_service, flight_service
    )


async def start_quick_calculation(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    lang = _lang(user)
    await state.clear()
    if user.selected_aircraft_id:
        await _begin(
            message,
            state,
            user,
            aircraft_service,
            flight_service,
            user.selected_aircraft_id,
        )
        return
    aircraft_list = await aircraft_service.list_aircraft(user.id)
    if not aircraft_list:
        await message.answer(t("no_aircraft_yet", lang))
        return
    await message.answer(
        t("select_aircraft_prompt", lang),
        reply_markup=aircraft_list_keyboard(aircraft_list, "quick_select"),
    )


@router.callback_query(F.data.startswith("quick_select:"))
async def quick_select_aircraft(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    aircraft_id = int(callback.data.split(":")[1])
    await callback.answer()
    await _begin(
        callback.message,
        state,
        user,
        aircraft_service,
        flight_service,
        aircraft_id,
    )


async def _begin(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
    aircraft_id: int,
    *,
    seed_values: dict | None = None,
) -> None:
    lang = _lang(user)
    try:
        aircraft, profile = await _load_profile_and_aircraft(
            user.id, aircraft_id, aircraft_service
        )
    except DomainError as exc:
        await message.answer(t("aircraft_profile_invalid", lang, detail=str(exc)))
        return
    if aircraft is None or profile is None:
        await message.answer(t("no_aircraft_selected", lang))
        return

    suspicious = suspicious_non_fuel_stations(profile)
    if suspicious:
        names = ", ".join(station.name for station in suspicious)
        await message.answer(t("fuel_station_type_error", lang, stations=names))
        return

    try:
        validate_quick_profile(profile)
        front_station = quick_station_for_type(
            profile, StationType.FRONT_SEATS, "Front seats"
        )
        rear_station = quick_station_for_type(
            profile, StationType.REAR_SEATS, "Rear seats"
        )
        baggage_station = quick_station_for_type(
            profile, StationType.BAGGAGE, "Baggage"
        )
    except DomainError as exc:
        await message.answer(str(exc), reply_markup=_advanced_only_keyboard(lang))
        return

    last = seed_values or await _last_quick_input(user.id, aircraft.id, flight_service)
    full_fuel = sum(
        (station.maximum_volume_gal for station in profile.fuel_stations), Decimal("0")
    )
    await state.update_data(
        aircraft_id=aircraft.id,
        tail_number=profile.tail_number,
        revision_number=profile.revision_number,
        has_front=front_station is not None,
        has_rear=rear_station is not None,
        has_baggage=baggage_station is not None,
        front_lb="0",
        rear_lb="0",
        baggage_lb="0",
        total_fuel_gal="0",
        last_front_lb=(last or {}).get("front_lb"),
        last_rear_lb=(last or {}).get("rear_lb"),
        last_baggage_lb=(last or {}).get("baggage_lb"),
        full_fuel_gal=compact_decimal(full_fuel),
        fuel_tank_labels=[
            short_tank_label(station.name) for station in profile.fuel_stations
        ],
        _nav_history=[],
    )
    label = f"{aircraft.nickname} ({profile.tail_number})" if aircraft.nickname else profile.tail_number
    await message.answer(f"Quick Check for {label}", reply_markup=ReplyKeyboardRemove())

    if front_station is not None:
        await goto(message, state, user, QuickCalcWizard.front, _ask_front, record_history=False)
    elif rear_station is not None:
        await goto(message, state, user, QuickCalcWizard.rear, _ask_rear, record_history=False)
    elif baggage_station is not None:
        await goto(
            message, state, user, QuickCalcWizard.baggage, _ask_baggage, record_history=False
        )
    else:
        await goto(message, state, user, QuickCalcWizard.fuel, _ask_fuel, record_history=False)


async def _ask_front(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await message.answer(
        t("quick_front_prompt", _lang(user)),
        reply_markup=_step_keyboard(
            _lang(user),
            last_value=data.get("last_front_lb"),
            unit="lb",
            # The front seat always carries at least the pilot, so a "None" shortcut here
            # would offer a combined weight of zero that can never actually be true.
            show_zero=False,
            show_back=await has_history(state),
        ),
    )


@router.message(QuickCalcWizard.front, F.text)
async def got_front(message: Message, state: FSMContext, user: User) -> None:
    try:
        value = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", _lang(user), detail=str(exc)))
        return
    await state.update_data(front_lb=str(value))
    await _advance_from_front(message, state, user)


@router.callback_query(QuickCalcWizard.front, F.data == "quick:use_last")
async def use_last_front(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.update_data(front_lb=data.get("last_front_lb") or "0")
    await callback.answer()
    await _advance_from_front(callback.message, state, user)


async def _advance_from_front(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    if data["has_rear"]:
        await goto(message, state, user, QuickCalcWizard.rear, _ask_rear)
    elif data["has_baggage"]:
        await goto(message, state, user, QuickCalcWizard.baggage, _ask_baggage)
    else:
        await goto(message, state, user, QuickCalcWizard.fuel, _ask_fuel)


async def _ask_rear(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await message.answer(
        t("quick_rear_prompt", _lang(user)),
        reply_markup=_step_keyboard(
            _lang(user),
            last_value=data.get("last_rear_lb"),
            unit="lb",
            show_back=await has_history(state),
        ),
    )


@router.message(QuickCalcWizard.rear, F.text)
async def got_rear(message: Message, state: FSMContext, user: User) -> None:
    try:
        value = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", _lang(user), detail=str(exc)))
        return
    await state.update_data(rear_lb=str(value))
    await _advance_from_rear(message, state, user)


@router.callback_query(QuickCalcWizard.rear, F.data == "quick:zero")
async def zero_rear(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(rear_lb="0")
    await callback.answer()
    await _advance_from_rear(callback.message, state, user)


@router.callback_query(QuickCalcWizard.rear, F.data == "quick:use_last")
async def use_last_rear(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.update_data(rear_lb=data.get("last_rear_lb") or "0")
    await callback.answer()
    await _advance_from_rear(callback.message, state, user)


async def _advance_from_rear(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    if data["has_baggage"]:
        await goto(message, state, user, QuickCalcWizard.baggage, _ask_baggage)
    else:
        await goto(message, state, user, QuickCalcWizard.fuel, _ask_fuel)


async def _ask_baggage(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await message.answer(
        t("quick_baggage_prompt", _lang(user)),
        reply_markup=_step_keyboard(
            _lang(user),
            last_value=data.get("last_baggage_lb"),
            unit="lb",
            show_back=await has_history(state),
        ),
    )


@router.message(QuickCalcWizard.baggage, F.text)
async def got_baggage(message: Message, state: FSMContext, user: User) -> None:
    try:
        value = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", _lang(user), detail=str(exc)))
        return
    await state.update_data(baggage_lb=str(value))
    await goto(message, state, user, QuickCalcWizard.fuel, _ask_fuel)


@router.callback_query(QuickCalcWizard.baggage, F.data == "quick:zero")
async def zero_baggage(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(baggage_lb="0")
    await callback.answer()
    await goto(callback.message, state, user, QuickCalcWizard.fuel, _ask_fuel)


@router.callback_query(QuickCalcWizard.baggage, F.data == "quick:use_last")
async def use_last_baggage(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    data = await state.get_data()
    await state.update_data(baggage_lb=data.get("last_baggage_lb") or "0")
    await callback.answer()
    await goto(callback.message, state, user, QuickCalcWizard.fuel, _ask_fuel)


async def _ask_fuel(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    tank_labels = data.get("fuel_tank_labels") or []
    await message.answer(
        t(
            "quick_fuel_prompt_tanks" if tank_labels else "quick_fuel_prompt",
            _lang(user),
            tanks=", ".join(tank_labels),
        ),
        reply_markup=_fuel_keyboard(
            _lang(user),
            full_gal=Decimal(data["full_fuel_gal"]),
            show_back=await has_history(state),
        ),
    )


@router.message(QuickCalcWizard.fuel, F.text)
async def got_fuel(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    try:
        value = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", _lang(user), detail=str(exc)))
        return
    await _finish_fuel(message, state, user, value, aircraft_service, flight_service)


@router.callback_query(QuickCalcWizard.fuel, F.data == "quick:full")
async def full_fuel(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    data = await state.get_data()
    await callback.answer()
    await _finish_fuel(
        callback.message,
        state,
        user,
        Decimal(data["full_fuel_gal"]),
        aircraft_service,
        flight_service,
    )


async def _finish_fuel(
    message: Message,
    state: FSMContext,
    user: User,
    value: Decimal,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    data = await state.get_data()
    full = Decimal(data["full_fuel_gal"])
    if value > full:
        await message.answer(
            t("fuel_capacity_exceeded", _lang(user), capacity=fmt(full, " gal"))
        )
        return
    await state.update_data(total_fuel_gal=str(value))
    # No separate "confirm your inputs, tap Calculate" screen -- the entered values are
    # summarized right above the result instead, and "Change load" (on the result message)
    # is the way back if something needs correcting.
    await _calculate_and_show_result(message, state, user, aircraft_service, flight_service)


@router.callback_query(QuickCalcWizard.review, F.data == "quick:edit")
async def quick_edit(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    data = await state.get_data()
    await callback.answer()
    await _begin(
        callback.message,
        state,
        user,
        aircraft_service,
        flight_service,
        data["aircraft_id"],
        seed_values={
            "front_lb": data.get("front_lb", "0"),
            "rear_lb": data.get("rear_lb", "0"),
            "baggage_lb": data.get("baggage_lb", "0"),
        },
    )


_STEP_RENDERERS = {
    QuickCalcWizard.front.state: _ask_front,
    QuickCalcWizard.rear.state: _ask_rear,
    QuickCalcWizard.baggage.state: _ask_baggage,
    QuickCalcWizard.fuel.state: _ask_fuel,
}


async def _cannot_go_back(message: Message, state: FSMContext, user: User) -> None:
    await message.answer(t("already_first_step", _lang(user)))


@router.callback_query(StateFilter(QuickCalcWizard), F.data == "quick:back")
async def quick_back(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await go_back(callback.message, state, user, _STEP_RENDERERS, _cannot_go_back)
    await callback.answer()


@router.callback_query(F.data == "quick:cancel")
async def quick_cancel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await callback.message.answer(
        t("cancelled", lang), reply_markup=main_menu_keyboard(lang)
    )
    await callback.answer()


@router.callback_query(F.data == "quick:main_menu")
async def quick_main_menu(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await callback.message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))
    await callback.answer()


_STATUS_TEXT = {
    LimitStatus.WITHIN: "✅ WITHIN LIMITS",
    LimitStatus.ON_LIMIT: "⚠️ ON LIMIT",
    LimitStatus.OUT_OF_LIMITS: "❌ OUT OF LIMITS",
}


def _cg_violation_direction(result: QuickCalculationResult) -> str | None:
    if result.fuel_range_status != FuelRangeStatus.OUT_ALL:
        return None
    if result.forward_check is None or result.aft_check is None:
        return None
    if not result.forward_check.weight_within_envelope:
        return None
    # The aft-most possible CG is still forward of the forward limit.
    if result.aft_check.forward_margin_in < 0:
        return "forward"
    # The forward-most possible CG is still aft of the aft limit.
    if result.forward_check.aft_margin_in < 0:
        return "aft"
    # This includes a weight outside the envelope's published weight range.
    return None


def _result_header(result: QuickCalculationResult) -> str:
    load_limit_out = result.weight_status == LimitStatus.OUT_OF_LIMITS
    if result.fuel_range_status == FuelRangeStatus.EXACT_SPLIT_REQUIRED:
        if load_limit_out:
            return "❌ LOAD LIMIT EXCEEDED — EXACT TANK SPLIT ALSO REQUIRED"
        return "⚠️ EXACT TANK SPLIT REQUIRED"
    if result.fuel_range_status is None:
        if not load_limit_out:
            return "⚠️ CG LIMITS NOT EVALUATED"
        return "❌ OVERWEIGHT — CG LIMITS NOT EVALUATED"

    direction = _cg_violation_direction(result)
    cg_out = result.fuel_range_status == FuelRangeStatus.OUT_ALL
    cg_weight_outside_range = (
        result.forward_check is not None
        and not result.forward_check.weight_within_envelope
    )
    if cg_weight_outside_range:
        if load_limit_out:
            return "❌ LOAD LIMIT EXCEEDED — WEIGHT OUTSIDE CG ENVELOPE RANGE"
        return "❌ WEIGHT OUTSIDE CG ENVELOPE RANGE"
    if load_limit_out and cg_out:
        suffix = f" — {direction.upper()} CG" if direction else ""
        return f"❌ LOAD AND CG OUT OF LIMITS{suffix}"
    if load_limit_out:
        return "❌ OVERWEIGHT"
    if cg_out:
        if direction == "forward":
            return "❌ FORWARD CG"
        if direction == "aft":
            return "❌ AFT CG"
        return "❌ OUTSIDE CG ENVELOPE"
    return _STATUS_TEXT[result.overall_status]


def _result_text(
    result: QuickCalculationResult, tail_number: str, lang: str
) -> str:
    lines = [_result_header(result), "", tail_number, "", "WEIGHT"]
    lines.append(
        f"{fmt(result.total_weight_lb, ' lb')} / {fmt(result.weight_limit_lb, ' lb')}"
    )
    if result.weight_margin_lb is not None:
        margin = result.weight_margin_lb
        word = "below maximum" if margin >= 0 else "over maximum"
        lines.append(f"{fmt(abs(margin), ' lb')} {word}")

    lines.extend(["", "CG"])
    if result.fuel_range_status is None:
        lines.append(f"Calculated CG: {fmt(result.cg_forward, ' in')}")
        lines.append("Limits not evaluated — no CG envelope is saved.")
    elif not result.forward_check.weight_within_envelope:
        if result.is_exact:
            lines.append(f"Calculated CG: {fmt(result.cg_forward, ' in')}")
        else:
            lines.append(
                f"Possible CG: {fmt(result.cg_forward, ' in')}–{fmt(result.cg_aft, ' in')}"
            )
        lines.append("CG envelope is not published at this aircraft weight.")
    elif result.is_exact:
        lines.append(fmt(result.cg_forward, " in"))
        lines.append(
            "Allowed: "
            f"{fmt(result.forward_check.forward_limit_in, ' in')}–"
            f"{fmt(result.forward_check.aft_limit_in, ' in')}"
        )
    else:
        lines.append(
            f"Possible CG: {fmt(result.cg_forward, ' in')}–{fmt(result.cg_aft, ' in')}"
        )
        lines.append(
            "Allowed: "
            f"{fmt(result.forward_check.forward_limit_in, ' in')}–"
            f"{fmt(result.forward_check.aft_limit_in, ' in')}"
        )

    direction = _cg_violation_direction(result)
    if direction == "forward":
        violation = result.aft_check.forward_limit_in - result.cg_aft
        lines.append(f"At least {fmt(violation, ' in')} forward of limit.")
    elif direction == "aft":
        violation = result.cg_forward - result.forward_check.aft_limit_in
        lines.append(f"At least {fmt(violation, ' in')} aft of limit.")
    elif result.fuel_range_status == FuelRangeStatus.EXACT_SPLIT_REQUIRED:
        lines.append("Some possible tank splits are within limits and some are not.")

    return "\n".join(lines)


def _quick_review_lines(
    data: dict,
    *,
    tail_number: str,
    front: Decimal,
    rear: Decimal,
    baggage: Decimal,
    total_fuel: Decimal,
    lang: str,
) -> list[str]:
    lines = [tail_number, ""]
    if data["has_front"]:
        lines.append(f"{t('quick_review_front', lang)}: {fmt(front, ' lb')}")
    if data["has_rear"]:
        lines.append(f"{t('quick_review_rear', lang)}: {fmt(rear, ' lb')}")
    if data["has_baggage"]:
        lines.append(f"{t('quick_review_baggage', lang)}: {fmt(baggage, ' lb')}")
    lines.append(f"{t('quick_review_fuel', lang)}: {fmt(total_fuel, ' gal')}")
    return lines


async def _calculate_and_show_result(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    lang = _lang(user)
    data = await state.get_data()
    try:
        aircraft, profile = await _load_profile_and_aircraft(
            user.id, data["aircraft_id"], aircraft_service
        )
    except DomainError as exc:
        await message.answer(t("aircraft_profile_invalid", lang, detail=str(exc)))
        return
    if aircraft is None or profile is None:
        await message.answer(t("no_aircraft_selected", lang))
        await state.clear()
        return

    front = Decimal(data["front_lb"])
    rear = Decimal(data["rear_lb"])
    baggage = Decimal(data["baggage_lb"])
    total_fuel = Decimal(data["total_fuel_gal"])
    try:
        result = run_quick_calculation(
            profile,
            front_lb=front,
            rear_lb=rear,
            baggage_lb=baggage,
            total_fuel_gal=total_fuel,
        )
    except DomainError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return

    quick_input = {
        "front_lb": data["front_lb"],
        "rear_lb": data["rear_lb"],
        "baggage_lb": data["baggage_lb"],
        "total_fuel_gal": data["total_fuel_gal"],
    }
    await flight_service.persist_quick_calculation(
        user_id=user.id,
        aircraft_id=aircraft.id,
        aircraft_revision_id=aircraft.active_revision_id,
        quick_input=quick_input,
        result=result,
    )

    # Keep review state so Change Load can restart with the same aircraft.
    await state.set_state(QuickCalcWizard.review)

    summary_lines = _quick_review_lines(
        data,
        tail_number=profile.tail_number,
        front=front,
        rear=rear,
        baggage=baggage,
        total_fuel=total_fuel,
        lang=lang,
    )
    await message.answer("\n".join(summary_lines))

    await message.answer(_result_text(result, profile.tail_number, lang))

    if result.fuel_range_status == FuelRangeStatus.EXACT_SPLIT_REQUIRED:
        await message.answer(t("exact_tank_split_required", lang))

    if result.overall_status == LimitStatus.OUT_OF_LIMITS:
        recommendations = flight_service.recommend_quick(
            profile,
            front_lb=front,
            rear_lb=rear,
            baggage_lb=baggage,
            total_fuel_gal=total_fuel,
        )
        await message.answer(recommendation_text(recommendations, lang))



@router.message(StateFilter(QuickCalcWizard))
async def unsupported_quick_message(message: Message, user: User) -> None:
    await message.answer(t("unsupported_wizard_message", _lang(user)))
