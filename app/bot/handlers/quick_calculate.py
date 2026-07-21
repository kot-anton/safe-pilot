"""The standard under-a-minute calculation flow.

A configured aircraft asks only for combined front-seat weight, combined rear-seat weight,
combined baggage weight, and total usable fuel. Tank-distribution uncertainty is handled by the
pure domain engine; this handler never invents an exact split or performs Weight & Balance math.
"""
from __future__ import annotations

import json
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.handlers._common import InputParseError, fmt, parse_decimal
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
from app.services.aircraft_service import (
    AircraftService,
    build_domain_profile,
    suspicious_non_fuel_stations,
)
from app.services.flight_service import FlightService

router = Router(name="quick_calculate")


def _lang(user: User) -> str:
    return user.language or "en"


async def _load_profile_and_aircraft(
    user_id: int, aircraft_id: int, aircraft_service: AircraftService
):
    aircraft = await aircraft_service.get_aircraft(user_id, aircraft_id)
    if aircraft is None or aircraft.active_revision_id is None:
        return None, None
    revision = await aircraft_service.get_revision_for_user(
        user_id, aircraft.active_revision_id
    )
    if revision is None:
        return None, None
    return aircraft, build_domain_profile(revision, aircraft)


async def _last_quick_input(
    user_id: int, aircraft_id: int, flight_service: FlightService
) -> dict | None:
    history = await flight_service.list_history(user_id, aircraft_id, limit=5)
    for calculation in history:
        if not calculation.calculation_engine_version.endswith("-quick"):
            continue
        try:
            return json.loads(calculation.input_snapshot_json)
        except (ValueError, TypeError):
            continue
    return None


def _step_keyboard(
    lang: str, *, last_value: str | None, unit: str
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="0", callback_data="quick:zero")]]
    if last_value is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Use last: {last_value} {unit}",
                    callback_data="quick:use_last",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="quick:cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fuel_keyboard(
    lang: str, *, full_gal: Decimal, last_value: str | None
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"Full — {fmt(full_gal, ' gal')}", callback_data="quick:full"
            )
        ],
        [InlineKeyboardButton(text="0", callback_data="quick:zero")],
    ]
    if last_value is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Use last: {last_value} gal", callback_data="quick:use_last"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="Exact tank split", callback_data="quick:advanced")]
    )
    rows.append(
        [InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="quick:cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Calculate", callback_data="quick:calculate")],
            [
                InlineKeyboardButton(text="Edit", callback_data="quick:edit"),
                InlineKeyboardButton(
                    text=t("btn_cancel", lang), callback_data="quick:cancel"
                ),
            ],
        ]
    )


def _advanced_only_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Advanced / Landing", callback_data="quick:advanced"
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
            [InlineKeyboardButton(text="Change Load", callback_data="quick:edit")],
            [
                InlineKeyboardButton(
                    text="Advanced / Landing", callback_data="quick:advanced"
                )
            ],
            [InlineKeyboardButton(text="Main Menu", callback_data="quick:main_menu")],
        ]
    )


@router.message(F.text.in_({t("menu_new_calc", "en"), t("menu_new_calc", "ru")}))
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
        await message.answer(f"Aircraft profile is invalid: {exc}")
        return
    if aircraft is None or profile is None:
        await message.answer(t("no_aircraft_selected", lang))
        return

    suspicious = suspicious_non_fuel_stations(profile)
    if suspicious:
        names = ", ".join(station.name for station in suspicious)
        await message.answer(
            "Aircraft profile error: these stations look like fuel tanks but are not configured "
            f"as FUEL: {names}. Edit the aircraft profile before calculating; fuel must be "
            "entered in gallons, not pounds."
        )
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
        last_total_fuel_gal=(last or {}).get("total_fuel_gal"),
        full_fuel_gal=str(full_fuel),
    )
    await message.answer(f"{profile.tail_number} (rev. {profile.revision_number})")

    if front_station is not None:
        await _ask_front(message, state, user)
    elif rear_station is not None:
        await _ask_rear(message, state, user)
    elif baggage_station is not None:
        await _ask_baggage(message, state, user)
    else:
        await _ask_fuel(message, state, user)


async def _ask_front(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.set_state(QuickCalcWizard.front)
    await message.answer(
        "Front seats — total weight in lb:",
        reply_markup=_step_keyboard(
            _lang(user), last_value=data.get("last_front_lb"), unit="lb"
        ),
    )


@router.message(QuickCalcWizard.front)
async def got_front(message: Message, state: FSMContext, user: User) -> None:
    try:
        value = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", _lang(user), detail=str(exc)))
        return
    await state.update_data(front_lb=str(value))
    await _advance_from_front(message, state, user)


@router.callback_query(QuickCalcWizard.front, F.data == "quick:zero")
async def zero_front(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(front_lb="0")
    await callback.answer()
    await _advance_from_front(callback.message, state, user)


@router.callback_query(QuickCalcWizard.front, F.data == "quick:use_last")
async def use_last_front(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.update_data(front_lb=data.get("last_front_lb") or "0")
    await callback.answer()
    await _advance_from_front(callback.message, state, user)


async def _advance_from_front(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    if data["has_rear"]:
        await _ask_rear(message, state, user)
    elif data["has_baggage"]:
        await _ask_baggage(message, state, user)
    else:
        await _ask_fuel(message, state, user)


async def _ask_rear(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.set_state(QuickCalcWizard.rear)
    await message.answer(
        "Rear seats — total weight in lb:",
        reply_markup=_step_keyboard(
            _lang(user), last_value=data.get("last_rear_lb"), unit="lb"
        ),
    )


@router.message(QuickCalcWizard.rear)
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
        await _ask_baggage(message, state, user)
    else:
        await _ask_fuel(message, state, user)


async def _ask_baggage(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.set_state(QuickCalcWizard.baggage)
    await message.answer(
        "Baggage — total weight in lb:",
        reply_markup=_step_keyboard(
            _lang(user), last_value=data.get("last_baggage_lb"), unit="lb"
        ),
    )


@router.message(QuickCalcWizard.baggage)
async def got_baggage(message: Message, state: FSMContext, user: User) -> None:
    try:
        value = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", _lang(user), detail=str(exc)))
        return
    await state.update_data(baggage_lb=str(value))
    await _ask_fuel(message, state, user)


@router.callback_query(QuickCalcWizard.baggage, F.data == "quick:zero")
async def zero_baggage(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.update_data(baggage_lb="0")
    await callback.answer()
    await _ask_fuel(callback.message, state, user)


@router.callback_query(QuickCalcWizard.baggage, F.data == "quick:use_last")
async def use_last_baggage(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    data = await state.get_data()
    await state.update_data(baggage_lb=data.get("last_baggage_lb") or "0")
    await callback.answer()
    await _ask_fuel(callback.message, state, user)


async def _ask_fuel(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.set_state(QuickCalcWizard.fuel)
    await message.answer(
        "Usable fuel on board — total US gallons:",
        reply_markup=_fuel_keyboard(
            _lang(user),
            full_gal=Decimal(data["full_fuel_gal"]),
            last_value=data.get("last_total_fuel_gal"),
        ),
    )


@router.message(QuickCalcWizard.fuel)
async def got_fuel(message: Message, state: FSMContext, user: User) -> None:
    try:
        value = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", _lang(user), detail=str(exc)))
        return
    await _finish_fuel(message, state, user, value)


@router.callback_query(QuickCalcWizard.fuel, F.data == "quick:full")
async def full_fuel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await callback.answer()
    await _finish_fuel(
        callback.message, state, user, Decimal(data["full_fuel_gal"])
    )


@router.callback_query(QuickCalcWizard.fuel, F.data == "quick:zero")
async def zero_fuel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _finish_fuel(callback.message, state, user, Decimal("0"))


@router.callback_query(QuickCalcWizard.fuel, F.data == "quick:use_last")
async def use_last_fuel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await callback.answer()
    if data.get("last_total_fuel_gal") is None:
        return
    await _finish_fuel(
        callback.message,
        state,
        user,
        Decimal(data["last_total_fuel_gal"]),
    )


async def _finish_fuel(
    message: Message, state: FSMContext, user: User, value: Decimal
) -> None:
    data = await state.get_data()
    full = Decimal(data["full_fuel_gal"])
    if value > full:
        await message.answer(
            t(
                "error_generic",
                _lang(user),
                detail=f"fuel exceeds combined usable capacity ({fmt(full, ' gal')})",
            )
        )
        return
    await state.update_data(total_fuel_gal=str(value))
    await _show_confirmation(message, state, user)


async def _show_confirmation(
    message: Message, state: FSMContext, user: User
) -> None:
    data = await state.get_data()
    lines = [data["tail_number"], ""]
    if data["has_front"]:
        lines.append(f"Front: {fmt(Decimal(data['front_lb']), ' lb')}")
    if data["has_rear"]:
        lines.append(f"Rear: {fmt(Decimal(data['rear_lb']), ' lb')}")
    if data["has_baggage"]:
        lines.append(f"Baggage: {fmt(Decimal(data['baggage_lb']), ' lb')}")
    lines.append(f"Fuel: {fmt(Decimal(data['total_fuel_gal']), ' gal')}")
    await state.set_state(QuickCalcWizard.review)
    await message.answer("\n".join(lines), reply_markup=_confirm_keyboard(_lang(user)))


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
            "total_fuel_gal": data.get("total_fuel_gal", "0"),
        },
    )


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
        if result.station_status == LimitStatus.OUT_OF_LIMITS:
            return "❌ STATION LOAD LIMIT EXCEEDED — CG LIMITS NOT EVALUATED"
        if result.zero_fuel_status == LimitStatus.OUT_OF_LIMITS:
            return "❌ ZERO-FUEL WEIGHT EXCEEDED — CG LIMITS NOT EVALUATED"
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
        if result.station_status == LimitStatus.OUT_OF_LIMITS:
            return "❌ STATION LOAD LIMIT EXCEEDED"
        if result.zero_fuel_status == LimitStatus.OUT_OF_LIMITS:
            return "❌ ZERO-FUEL WEIGHT EXCEEDED"
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

    if result.zero_fuel_limit_lb is not None:
        lines.append(
            f"Zero-fuel: {fmt(result.zero_fuel_weight_lb, ' lb')} / "
            f"{fmt(result.zero_fuel_limit_lb, ' lb')}"
        )
    for station_violation in result.station_violations:
        excess = (
            station_violation.actual_weight_lb
            - station_violation.maximum_weight_lb
        )
        lines.append(
            f"{station_violation.station_name}: "
            f"{fmt(station_violation.actual_weight_lb, ' lb')} / "
            f"{fmt(station_violation.maximum_weight_lb, ' lb')} "
            f"({fmt(excess, ' lb')} over station limit)"
        )

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

    lines.extend(["", t("result_footer", lang)])
    return "\n".join(lines)


@router.callback_query(QuickCalcWizard.review, F.data == "quick:calculate")
async def quick_calculate_confirm(
    callback: CallbackQuery,
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
        await callback.message.answer(f"Aircraft profile is invalid: {exc}")
        await callback.answer()
        return
    if aircraft is None or profile is None:
        await callback.answer(t("no_aircraft_selected", lang), show_alert=True)
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
        await callback.message.answer(t("error_generic", lang, detail=str(exc)))
        await callback.answer()
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

    await callback.message.answer(_result_text(result, profile.tail_number, lang))

    if result.fuel_range_status == FuelRangeStatus.EXACT_SPLIT_REQUIRED:
        await callback.message.answer(
            "Enter the actual gallons in each tank for an exact result."
        )

    if result.overall_status == LimitStatus.OUT_OF_LIMITS:
        recommendations = flight_service.recommend_quick(
            profile,
            front_lb=front,
            rear_lb=rear,
            baggage_lb=baggage,
            total_fuel_gal=total_fuel,
        )
        if recommendations:
            lines = [t("recommendations_header", lang)]
            for index, recommendation in enumerate(recommendations, start=1):
                lines.append(f"{index}. {recommendation.describe()}")
                if recommendation.note:
                    lines.append(f"   {recommendation.note}")
            await callback.message.answer("\n".join(lines))
        else:
            await callback.message.answer(t("no_recommendations", lang))

    await callback.message.answer(
        "What next?", reply_markup=_result_keyboard(lang)
    )
    # Keep review state so Change Load can restart with the same aircraft.
    await callback.answer()
