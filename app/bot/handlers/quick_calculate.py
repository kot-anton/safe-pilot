"""The standard "under a minute" calculation flow: front seats, rear seats, baggage, total
fuel. Questions for stations the aircraft doesn't have (e.g. no rear seats) are skipped
entirely. Fuel is a single total-gallons number -- see app.domain.fuel_allocation /
app.domain.quick_calculation for how that's turned into an exact CG or an honest range.
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
from app.domain.fuel_allocation import FuelRangeStatus, FuelTankSpec
from app.domain.models import CalculationInput, FuelStationInput, LoadItemInput, StationType
from app.domain.quick_calculation import QuickCalculationResult, run_quick_calculation
from app.services.aircraft_service import AircraftService, build_domain_profile
from app.services.flight_service import FlightService

router = Router(name="quick_calculate")


def _lang(user: User) -> str:
    return user.language or "en"


async def _load_profile_and_aircraft(user_id: int, aircraft_id: int, aircraft_service: AircraftService):
    aircraft = await aircraft_service.get_aircraft(user_id, aircraft_id)
    if aircraft is None or aircraft.active_revision_id is None:
        return None, None
    revision = await aircraft_service.get_revision_for_user(user_id, aircraft.active_revision_id)
    if revision is None:
        return None, None
    return aircraft, build_domain_profile(revision, aircraft)


async def _last_quick_input(user_id: int, aircraft_id: int, flight_service: FlightService) -> dict | None:
    history = await flight_service.list_history(user_id, aircraft_id, limit=5)
    for calc in history:
        if not calc.calculation_engine_version.endswith("-quick"):
            continue
        try:
            return json.loads(calc.input_snapshot_json)
        except (ValueError, TypeError):
            continue
    return None


def _step_keyboard(lang: str, *, last_value: str | None, unit: str) -> InlineKeyboardMarkup:
    rows = []
    if last_value is not None:
        rows.append([InlineKeyboardButton(text=f"Use last: {last_value} {unit}", callback_data="quick:use_last")])
    rows.append(
        [
            InlineKeyboardButton(text="0", callback_data="quick:zero"),
            InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="quick:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fuel_keyboard(lang: str, *, full_gal: Decimal, last_value: str | None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"Full -- {full_gal:.0f} gal", callback_data="quick:full")]]
    if last_value is not None:
        rows.append([InlineKeyboardButton(text=f"Use last: {last_value} gal", callback_data="quick:use_last")])
    rows.append(
        [
            InlineKeyboardButton(text="0", callback_data="quick:zero"),
            InlineKeyboardButton(text="Exact tank split", callback_data="quick:advanced"),
        ]
    )
    rows.append([InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="quick:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Calculate", callback_data="quick:calculate")],
            [
                InlineKeyboardButton(text="Edit", callback_data="quick:edit"),
                InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="quick:cancel"),
            ],
        ]
    )


def _result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Change Load", callback_data="quick:edit")],
            [InlineKeyboardButton(text="Advanced / Landing", callback_data="quick:advanced")],
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
        await _begin(message, state, user, aircraft_service, flight_service, user.selected_aircraft_id)
        return
    aircraft_list = await aircraft_service.list_aircraft(user.id)
    if not aircraft_list:
        await message.answer(t("no_aircraft_yet", lang))
        return
    await message.answer(
        t("select_aircraft_prompt", lang), reply_markup=aircraft_list_keyboard(aircraft_list, "quick_select")
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
    await _begin(callback.message, state, user, aircraft_service, flight_service, aircraft_id)


async def _begin(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
    aircraft_id: int,
) -> None:
    lang = _lang(user)
    aircraft, profile = await _load_profile_and_aircraft(user.id, aircraft_id, aircraft_service)
    if aircraft is None or profile is None:
        await message.answer(t("no_aircraft_selected", lang))
        return

    has_front = any(s.station_type == StationType.FRONT_SEATS for s in profile.stations)
    has_rear = any(s.station_type == StationType.REAR_SEATS for s in profile.stations)
    has_baggage = any(s.station_type == StationType.BAGGAGE for s in profile.stations)
    last = await _last_quick_input(user.id, aircraft.id, flight_service)

    await state.update_data(
        aircraft_id=aircraft.id,
        tail_number=profile.tail_number,
        revision_number=profile.revision_number,
        has_front=has_front,
        has_rear=has_rear,
        has_baggage=has_baggage,
        front_lb="0",
        rear_lb="0",
        baggage_lb="0",
        total_fuel_gal="0",
        last_front_lb=(last or {}).get("front_lb"),
        last_rear_lb=(last or {}).get("rear_lb"),
        last_baggage_lb=(last or {}).get("baggage_lb"),
        last_total_fuel_gal=(last or {}).get("total_fuel_gal"),
        full_fuel_gal=str(sum((s.maximum_volume_gal for s in profile.fuel_stations), Decimal("0"))),
    )
    await message.answer(f"{profile.tail_number} (rev. {profile.revision_number})")

    if has_front:
        await _ask_front(message, state, user)
    elif has_rear:
        await _ask_rear(message, state, user)
    elif has_baggage:
        await _ask_baggage(message, state, user)
    else:
        await _ask_fuel(message, state, user)


async def _ask_front(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.set_state(QuickCalcWizard.front)
    await message.answer(
        "Front seats -- total weight in lb",
        reply_markup=_step_keyboard(_lang(user), last_value=data.get("last_front_lb"), unit="lb"),
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
        "Rear seats -- total weight in lb",
        reply_markup=_step_keyboard(_lang(user), last_value=data.get("last_rear_lb"), unit="lb"),
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
        "Baggage -- total weight in lb",
        reply_markup=_step_keyboard(_lang(user), last_value=data.get("last_baggage_lb"), unit="lb"),
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
async def use_last_baggage(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.update_data(baggage_lb=data.get("last_baggage_lb") or "0")
    await callback.answer()
    await _ask_fuel(callback.message, state, user)


async def _ask_fuel(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await state.set_state(QuickCalcWizard.fuel)
    await message.answer(
        "Usable fuel on board -- total US gallons",
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


@router.callback_query(QuickCalcWizard.fuel, F.data == "quick:zero")
async def zero_fuel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _finish_fuel(callback.message, state, user, Decimal("0"))


@router.callback_query(QuickCalcWizard.fuel, F.data == "quick:full")
async def full_fuel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await callback.answer()
    await _finish_fuel(callback.message, state, user, Decimal(data["full_fuel_gal"]))


@router.callback_query(QuickCalcWizard.fuel, F.data == "quick:use_last")
async def use_last_fuel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    await callback.answer()
    if not data.get("last_total_fuel_gal"):
        return
    await _finish_fuel(callback.message, state, user, Decimal(data["last_total_fuel_gal"]))


async def _finish_fuel(message: Message, state: FSMContext, user: User, value: Decimal) -> None:
    await state.update_data(total_fuel_gal=str(value))
    await _show_confirmation(message, state, user)


async def _show_confirmation(message: Message, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    lines = [data["tail_number"], ""]
    if data["has_front"]:
        lines.append(f"Front: {data['front_lb']} lb")
    if data["has_rear"]:
        lines.append(f"Rear: {data['rear_lb']} lb")
    if data["has_baggage"]:
        lines.append(f"Baggage: {data['baggage_lb']} lb")
    lines.append(f"Fuel: {data['total_fuel_gal']} gal")
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
    await _begin(callback.message, state, user, aircraft_service, flight_service, data["aircraft_id"])


@router.callback_query(F.data == "quick:cancel")
async def quick_cancel(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.clear()
    lang = _lang(user)
    await callback.message.answer(t("cancelled", lang), reply_markup=main_menu_keyboard(lang))
    await callback.answer()


_STATUS_TEXT = {
    LimitStatus.WITHIN: "✅ WITHIN LIMITS",
    LimitStatus.ON_LIMIT: "⚠️ ON LIMIT",
    LimitStatus.OUT_OF_LIMITS: "❌ OUT OF LIMITS",
}


def _result_text(result: QuickCalculationResult, tail_number: str, lang: str) -> str:
    lines = []
    if result.fuel_range_status == FuelRangeStatus.EXACT_SPLIT_REQUIRED:
        lines.append("⚠️ EXACT TANK SPLIT REQUIRED")
    elif result.weight_status == LimitStatus.OUT_OF_LIMITS:
        lines.append("❌ OVERWEIGHT")
    elif result.forward_check is not None and result.forward_check.status == LimitStatus.OUT_OF_LIMITS:
        lines.append("❌ FORWARD CG")
    elif result.aft_check is not None and result.aft_check.status == LimitStatus.OUT_OF_LIMITS:
        lines.append("❌ AFT CG")
    else:
        lines.append(_STATUS_TEXT[result.overall_status])
    lines.append("")
    lines.append(tail_number)
    lines.append("")
    lines.append("WEIGHT")
    lines.append(f"{fmt(result.total_weight_lb, ' lb')} / {fmt(result.weight_limit_lb, ' lb')}")
    if result.weight_margin_lb is not None:
        margin = result.weight_margin_lb
        word = "below maximum" if margin >= 0 else "over maximum"
        lines.append(f"{fmt(abs(margin), ' lb')} {word}")
    lines.append("")
    lines.append("CG")
    if result.fuel_range_status is None:
        lines.append(f"{fmt(result.cg_forward, ' in')} (CG limits not evaluated -- no envelope on file)")
    elif result.is_exact:
        lines.append(f"{fmt(result.cg_forward, ' in')}")
        lines.append(f"Allowed: {fmt(result.forward_check.forward_limit_in, ' in')}-{fmt(result.forward_check.aft_limit_in, ' in')}")
    else:
        lines.append(f"Possible CG: {fmt(result.cg_forward, ' in')}-{fmt(result.cg_aft, ' in')}")
        lines.append(f"Allowed: {fmt(result.forward_check.forward_limit_in, ' in')}-{fmt(result.forward_check.aft_limit_in, ' in')}")
        if result.fuel_range_status == FuelRangeStatus.EXACT_SPLIT_REQUIRED:
            lines.append("Some possible fuel splits are within limits and some are not.")
    lines.append("")
    lines.append(t("result_footer", lang))
    return "\n".join(lines)


def _build_recommendation_input(profile, data: dict, result: QuickCalculationResult) -> CalculationInput | None:
    """Recommendations need one concrete fuel split to recalculate against. When the split is
    unknown, the least favorable (worse of the two boundary CGs) allocation is used, so any
    recommendation offered is verified to work in the worst case, not just a lucky one."""
    loads = []
    if data["has_front"]:
        front_station = next(s for s in profile.stations if s.station_type == StationType.FRONT_SEATS)
        loads.append(LoadItemInput(station_id=front_station.station_id, weight_lb=Decimal(data["front_lb"])))
    if data["has_rear"]:
        rear_station = next(s for s in profile.stations if s.station_type == StationType.REAR_SEATS)
        loads.append(LoadItemInput(station_id=rear_station.station_id, weight_lb=Decimal(data["rear_lb"])))
    if data["has_baggage"]:
        baggage_station = next(s for s in profile.stations if s.station_type == StationType.BAGGAGE)
        loads.append(LoadItemInput(station_id=baggage_station.station_id, weight_lb=Decimal(data["baggage_lb"])))

    use_max = result.aft_check is not None and result.aft_check.status == LimitStatus.OUT_OF_LIMITS
    allocation = result.fuel_allocation.max_allocation if use_max else result.fuel_allocation.min_allocation
    fuel = [
        FuelStationInput(station_id=sid, starting_gal=gal)
        for sid, gal in allocation.gallons_by_station.items()
    ]
    return CalculationInput(loads=loads, fuel=fuel)


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
    aircraft, profile = await _load_profile_and_aircraft(user.id, data["aircraft_id"], aircraft_service)
    if aircraft is None or profile is None:
        await callback.answer(t("no_aircraft_selected", lang), show_alert=True)
        await state.clear()
        return

    try:
        result = run_quick_calculation(
            profile,
            front_lb=Decimal(data["front_lb"]),
            rear_lb=Decimal(data["rear_lb"]),
            baggage_lb=Decimal(data["baggage_lb"]),
            total_fuel_gal=Decimal(data["total_fuel_gal"]),
        )
    except Exception as exc:
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

    if result.overall_status != LimitStatus.WITHIN:
        calc_input = _build_recommendation_input(profile, data, result)
        recs = flight_service.recommend(
            profile, calc_input, min_fuel_gal=None, allow_added_ballast_recommendations=aircraft.allow_added_ballast_recommendations
        )
        if recs:
            rec_lines = ["CORRECTION"]
            for rec in recs[:1]:
                rec_lines.append(rec.describe())
                if rec.note:
                    rec_lines.append(rec.note)
            await callback.message.answer("\n".join(rec_lines))

    await callback.message.answer("What next?", reply_markup=_result_keyboard())
    # Deliberately not clearing state here: it stays QuickCalcWizard.review so the "Change
    # Load" button on the result (same callback as the earlier confirm screen) still works.
    await callback.answer()
