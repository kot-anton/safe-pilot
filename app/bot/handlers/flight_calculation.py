"""New Calculation flow: collect loads and fuel for the active aircraft, run the domain
calculator, persist a FlightCalculation snapshot, and render the result.

Navigation: this flow revisits the same FSM states once per station/tank (station #1's
load question and station #2's load question are both `FlightWizard.load_at_station`), so
plain state-name history (as used in aircraft_wizard.py) isn't enough to tell them apart.
Instead each step pushes a small checkpoint -- `("load", index)` or
`("fuel", index, field)` -- via `push_checkpoint`/`pop_checkpoint`, and the "◀ Back" button
re-renders whichever checkpoint comes off the stack.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

from app.bot.handlers._common import InputParseError, fmt, parse_decimal
from app.bot.handlers.wizard_nav import pop_checkpoint, push_checkpoint
from app.bot.keyboards.common import (
    aircraft_list_keyboard,
    confirm_keyboard,
    main_menu_keyboard,
    skip_cancel_keyboard,
)
from app.bot.states.flight_wizard import FlightWizard
from app.bot.texts.i18n import t
from app.database.models import User
from app.domain.envelope import LimitStatus
from app.domain.exceptions import DomainError
from app.domain.models import CalculationInput, CalculationResult, FuelStationInput, LoadItemInput, PhaseResult, StationType
from app.domain.recommendations import Recommendation
from app.services.aircraft_service import AircraftService, suspicious_non_fuel_stations
from app.services.flight_service import FlightService

router = Router(name="flight_calculation")


def _lang(user: User) -> str:
    return user.language or "en"


async def _load_profile_and_aircraft(user_id: int, aircraft_id: int, aircraft_service: AircraftService):
    aircraft = await aircraft_service.get_aircraft(user_id, aircraft_id)
    if aircraft is None or aircraft.active_revision_id is None:
        return None, None
    revision = await aircraft_service.get_revision_for_user(user_id, aircraft.active_revision_id)
    if revision is None:
        return None, None
    from app.services.aircraft_service import build_domain_profile

    return aircraft, build_domain_profile(revision, aircraft)


def _history_decimal(value, *, allow_negative: bool = False) -> str | None:
    """Return a safe, canonical decimal from a stored history snapshot."""
    try:
        decimal = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not decimal.is_finite() or (not allow_negative and decimal < 0):
        return None
    return str(decimal)


async def _last_advanced_input(
    user_id: int, aircraft_id: int, flight_service: FlightService
) -> dict | None:
    """Load the latest valid full-calculation values for station-aware shortcuts.

    History may include Quick calculations and legacy/malformed snapshots. Only a structured
    Advanced snapshot is considered, and callers still match values against the current
    aircraft's station IDs and limits before offering them.
    """
    history = await flight_service.list_history(user_id, aircraft_id, limit=10)
    for calculation in history:
        if str(getattr(calculation, "calculation_engine_version", "")).endswith(
            "-quick"
        ):
            continue
        try:
            snapshot = json.loads(calculation.input_snapshot_json)
        except (ValueError, TypeError):
            continue
        if not isinstance(snapshot, dict):
            continue
        load_items = snapshot.get("loads")
        fuel_items = snapshot.get("fuel")
        if not isinstance(load_items, list) or not isinstance(fuel_items, list):
            continue

        loads: dict[str, str] = {}
        load_arms: dict[str, str] = {}
        fuel_starting: dict[str, str] = {}
        for item in load_items:
            if not isinstance(item, dict) or not isinstance(item.get("station_id"), str):
                continue
            station_id = item["station_id"]
            weight = _history_decimal(item.get("weight_lb"))
            arm = _history_decimal(item.get("arm_in"), allow_negative=True)
            if weight is not None:
                loads[station_id] = weight
            if arm is not None:
                load_arms[station_id] = arm
        for item in fuel_items:
            if not isinstance(item, dict) or not isinstance(item.get("station_id"), str):
                continue
            starting = _history_decimal(item.get("starting_gal"))
            if starting is not None:
                fuel_starting[item["station_id"]] = starting
        return {
            "loads": loads,
            "load_arms": load_arms,
            "fuel_starting": fuel_starting,
        }
    return None


def _load_keyboard(
    lang: str,
    *,
    last_value: str | None,
    last_arm: str | None,
    adjustable: bool,
    show_back: bool,
) -> InlineKeyboardMarkup:
    rows = []
    if last_value is not None and (not adjustable or last_arm is not None):
        unit = "lb" if not adjustable else f"lb @ {last_arm} in"
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_use_last", lang, value=last_value, unit=unit),
                    callback_data="flight:use_last_load",
                )
            ]
        )
    footer = []
    if show_back:
        footer.append(
            InlineKeyboardButton(text=t("btn_back", lang), callback_data="wizard:back")
        )
    footer.append(
        InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel")
    )
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fuel_start_keyboard(
    lang: str,
    *,
    capacity: Decimal,
    last_value: str | None,
    show_back: bool = True,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=t("btn_full_tank", lang, value=fmt(capacity, " gal")),
                callback_data="flight:full_fuel",
            )
        ]
    ]
    if last_value is not None and Decimal(last_value) <= capacity:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_use_last", lang, value=last_value, unit="gal"),
                    callback_data="flight:use_last_fuel",
                )
            ]
        )
    footer = []
    if show_back:
        footer.append(
            InlineKeyboardButton(text=t("btn_back", lang), callback_data="wizard:back")
        )
    footer.append(
        InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel")
    )
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def start_calculation(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    """The full per-tank/per-station "Advanced" calculation -- optional enroute burn,
    exact per-tank amounts, ramp/takeoff/landing. Reached through the calculation-mode choice
    or from a quick-calculation result; the standard flow remains the shorter combined-load
    calculation for routine use."""
    lang = _lang(user)
    await state.clear()
    if user.selected_aircraft_id:
        await _begin_for_aircraft(
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
    await state.set_state(FlightWizard.select_aircraft)
    await message.answer(
        t("select_aircraft_prompt", lang), reply_markup=aircraft_list_keyboard(aircraft_list, "calc_select")
    )


@router.callback_query(F.data == "quick:advanced")
async def advanced_from_quick(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    await callback.answer()
    await start_calculation(
        callback.message, state, user, aircraft_service, flight_service
    )


@router.callback_query(FlightWizard.select_aircraft, F.data.startswith("calc_select:"))
async def calc_select_aircraft(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    aircraft_id = int(callback.data.split(":")[1])
    await _begin_for_aircraft(
        callback.message,
        state,
        user,
        aircraft_service,
        flight_service,
        aircraft_id,
    )
    await callback.answer()


async def _begin_for_aircraft(
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

    non_fuel_stations = [s for s in profile.stations if s.station_type != StationType.FUEL]
    fuel_stations = profile.fuel_stations
    last = seed_values or await _last_advanced_input(
        user.id, aircraft.id, flight_service
    )
    last_load_values = {}
    last_load_arms = {}
    for station in non_fuel_stations:
        weight_text = (last or {}).get("loads", {}).get(station.station_id)
        if weight_text is None:
            continue
        weight = Decimal(weight_text)
        if station.maximum_weight_lb is not None and weight > station.maximum_weight_lb:
            continue
        if station.is_adjustable_arm:
            arm_text = (last or {}).get("load_arms", {}).get(station.station_id)
            if arm_text is None:
                continue
            arm = Decimal(arm_text)
            if not station.minimum_arm_in <= arm <= station.maximum_arm_in:
                continue
            last_load_arms[station.station_id] = arm_text
        last_load_values[station.station_id] = weight_text
    last_fuel_starting = {
        station.station_id: value
        for station in fuel_stations
        if (
            (value := (last or {}).get("fuel_starting", {}).get(station.station_id))
            is not None
            and Decimal(value) <= station.maximum_volume_gal
        )
    }

    await state.update_data(
        aircraft_id=aircraft.id,
        revision_number=profile.revision_number,
        tail_number=profile.tail_number,
        non_fuel_station_ids=[s.station_id for s in non_fuel_stations],
        non_fuel_station_names={s.station_id: s.name for s in non_fuel_stations},
        non_fuel_station_types={s.station_id: s.station_type.value for s in non_fuel_stations},
        non_fuel_station_adjustable={s.station_id: s.is_adjustable_arm for s in non_fuel_stations},
        non_fuel_station_default_arms={s.station_id: str(s.default_arm_in) for s in non_fuel_stations},
        non_fuel_station_min_arms={
            s.station_id: str(s.minimum_arm_in) if s.minimum_arm_in is not None else None
            for s in non_fuel_stations
        },
        non_fuel_station_max_arms={
            s.station_id: str(s.maximum_arm_in) if s.maximum_arm_in is not None else None
            for s in non_fuel_stations
        },
        fuel_station_ids=[s.station_id for s in fuel_stations],
        fuel_station_names={s.station_id: s.name for s in fuel_stations},
        fuel_station_capacities={
            s.station_id: str(s.maximum_volume_gal) for s in fuel_stations
        },
        last_load_values=last_load_values,
        last_load_arms=last_load_arms,
        last_fuel_starting=last_fuel_starting,
        load_index=0,
        fuel_index=0,
        loads={},
        load_arms={},
        fuel={},
        _nav_history=[],
    )
    await message.answer(profile.tail_number, reply_markup=ReplyKeyboardRemove())

    if not non_fuel_stations:
        await _ask_next_fuel_starting(message, state, user, 0)
        return

    await _render_load_prompt(message, state, user, 0, show_back=False)


async def _render_load_prompt(message: Message, state: FSMContext, user: User, index: int, *, show_back: bool = True) -> None:
    await state.update_data(load_index=index)
    await state.set_state(FlightWizard.load_at_station)
    data = await state.get_data()
    lang = _lang(user)
    station_ids = data["non_fuel_station_ids"]
    station_id = station_ids[index]
    name = data.get("non_fuel_station_names", {}).get(station_id, station_id)
    if data.get("non_fuel_station_adjustable", {}).get(station_id, False):
        minimum = data.get("non_fuel_station_min_arms", {}).get(station_id)
        maximum = data.get("non_fuel_station_max_arms", {}).get(station_id)
        prompt = t(
            "ask_load_at_adjustable_station",
            lang,
            station=name,
            minimum=minimum,
            maximum=maximum,
        )
    else:
        prompt = t("ask_load_at_station", lang, station=name)
    adjustable = data.get("non_fuel_station_adjustable", {}).get(station_id, False)
    await message.answer(
        prompt,
        reply_markup=_load_keyboard(
            lang,
            last_value=data.get("last_load_values", {}).get(station_id),
            last_arm=data.get("last_load_arms", {}).get(station_id),
            adjustable=adjustable,
            show_back=show_back,
        ),
    )


_FUEL_FIELD_STATE: dict[str, tuple[State, str]] = {
    "starting": (FlightWizard.fuel_starting, "ask_fuel_starting"),
    "enroute": (FlightWizard.fuel_enroute, "ask_fuel_enroute"),
}


async def _render_fuel_prompt(message: Message, state: FSMContext, user: User, index: int, field: str) -> None:
    await state.update_data(fuel_index=index)
    target_state, text_key = _FUEL_FIELD_STATE[field]
    await state.set_state(target_state)
    data = await state.get_data()
    lang = _lang(user)
    fuel_ids = data["fuel_station_ids"]
    station_id = fuel_ids[index]
    name = data.get("fuel_station_names", {}).get(station_id, station_id)
    if field == "starting":
        capacity = Decimal(data["fuel_station_capacities"][station_id])
        keyboard = _fuel_start_keyboard(
            lang,
            capacity=capacity,
            last_value=data.get("last_fuel_starting", {}).get(station_id),
            show_back=bool(data.get("_nav_history")),
        )
        kwargs = {
            "station": name,
            "capacity": fmt(capacity, " gal"),
        }
    else:
        keyboard = skip_cancel_keyboard(lang)
        starting = Decimal(data.get("fuel", {}).get(station_id, {}).get("starting_gal", "0"))
        kwargs = {"station": name, "available": fmt(starting, " gal")}
    await message.answer(t(text_key, lang, **kwargs), reply_markup=keyboard)


async def _cannot_go_back(callback: CallbackQuery, user: User) -> None:
    await callback.answer(t("already_first_step", _lang(user)))


@router.callback_query(StateFilter(FlightWizard), F.data == "wizard:back")
async def flight_back(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    checkpoint = await pop_checkpoint(state)
    if checkpoint is None:
        await _cannot_go_back(callback, user)
        return
    kind = checkpoint[0]
    if kind == "load":
        await _render_load_prompt(callback.message, state, user, checkpoint[1])
    else:
        await _render_fuel_prompt(callback.message, state, user, checkpoint[1], checkpoint[2])
    await callback.answer()


@router.message(FlightWizard.load_at_station, F.text)
async def got_load_at_station(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    station_ids = data["non_fuel_station_ids"]
    index = data["load_index"]
    station_id = station_ids[index]
    adjustable = data.get("non_fuel_station_adjustable", {}).get(station_id, False)
    try:
        weight, arm = _parse_load_entry(
            message.text,
            adjustable=adjustable,
            default_arm=Decimal(data["non_fuel_station_default_arms"][station_id]),
        )
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await _store_load_and_advance(message, state, user, weight, arm)


async def _store_load_and_advance(
    message: Message,
    state: FSMContext,
    user: User,
    weight: Decimal,
    arm: Decimal | None,
) -> None:
    lang = _lang(user)
    data = await state.get_data()
    station_ids = data["non_fuel_station_ids"]
    index = data["load_index"]
    station_id = station_ids[index]
    loads = data["loads"]
    load_arms = data.get("load_arms", {})
    if arm is not None:
        minimum = Decimal(data["non_fuel_station_min_arms"][station_id])
        maximum = Decimal(data["non_fuel_station_max_arms"][station_id])
        if not minimum <= arm <= maximum:
            await message.answer(
                t(
                    "error_generic",
                    lang,
                    detail=f"ARM must be within {minimum}-{maximum} in",
                )
            )
            return
        load_arms[station_id] = str(arm)
    loads[station_id] = str(weight)
    await state.update_data(loads=loads, load_arms=load_arms)
    await push_checkpoint(state, ("load", index))
    await _ask_next_load_or_fuel(message, state, user, index + 1)


@router.callback_query(
    FlightWizard.load_at_station, F.data == "flight:use_last_load"
)
async def use_last_load(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    data = await state.get_data()
    station_id = data["non_fuel_station_ids"][data["load_index"]]
    last_value = data.get("last_load_values", {}).get(station_id)
    if last_value is None:
        await callback.answer()
        return
    arm = None
    if data.get("non_fuel_station_adjustable", {}).get(station_id, False):
        last_arm = data.get("last_load_arms", {}).get(station_id)
        if last_arm is None:
            await callback.answer()
            return
        arm = Decimal(last_arm)
    await callback.answer()
    await _store_load_and_advance(
        callback.message, state, user, Decimal(last_value), arm
    )


def _parse_load_entry(
    text: str, *, adjustable: bool, default_arm: Decimal
) -> tuple[Decimal, Decimal | None]:
    """Parse a fixed load or ``weight / ARM`` for an adjustable station.

    A typed zero is accepted without an ARM and uses the profile's default ARM; zero moment is
    unaffected, while keeping an ARM value satisfies the domain model consistently.
    """
    if not adjustable:
        return parse_decimal(text), None

    stripped = text.strip()
    separators = re.split(r"\s*(?:/|;)\s*", stripped)
    if len(separators) == 1:
        separators = stripped.split()
    if len(separators) == 1:
        weight = parse_decimal(separators[0])
        if weight == 0:
            return weight, default_arm
        raise InputParseError("enter both weight and actual ARM, for example: 25 / 90")
    if len(separators) != 2:
        raise InputParseError("expected: weight / ARM")
    return parse_decimal(separators[0]), parse_decimal(separators[1], allow_negative=True)


async def _ask_next_load_or_fuel(message: Message, state: FSMContext, user: User, index: int) -> None:
    data = await state.get_data()
    station_ids = data["non_fuel_station_ids"]
    if index < len(station_ids):
        await _render_load_prompt(message, state, user, index)
        return
    await _ask_next_fuel_starting(message, state, user, 0)


@router.callback_query(FlightWizard.load_at_station, F.data == "wizard:skip")
async def skip_load_at_station(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    station_ids = data["non_fuel_station_ids"]
    index = data["load_index"]
    loads = data["loads"]
    load_arms = data.get("load_arms", {})
    station_id = station_ids[index]
    loads[station_id] = "0"
    if data.get("non_fuel_station_adjustable", {}).get(station_id, False):
        load_arms[station_id] = data["non_fuel_station_default_arms"][station_id]
    await state.update_data(loads=loads, load_arms=load_arms)
    await push_checkpoint(state, ("load", index))
    await callback.answer()
    await _ask_next_load_or_fuel(callback.message, state, user, index + 1)


async def _ask_next_fuel_starting(message: Message, state: FSMContext, user: User, index: int) -> None:
    data = await state.get_data()
    fuel_ids = data["fuel_station_ids"]
    if index >= len(fuel_ids):
        await _show_flight_review(message, state, user)
        return
    await _render_fuel_prompt(message, state, user, index, "starting")


@router.message(FlightWizard.fuel_starting, F.text)
async def got_fuel_starting(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        gal = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await _store_starting_fuel_and_advance(message, state, user, gal)


async def _store_starting_fuel_and_advance(
    message: Message,
    state: FSMContext,
    user: User,
    gal: Decimal,
) -> None:
    lang = _lang(user)
    data = await state.get_data()
    fuel_ids = data["fuel_station_ids"]
    index = data["fuel_index"]
    station_id = fuel_ids[index]
    capacity = Decimal(data["fuel_station_capacities"][station_id])
    if gal > capacity:
        await message.answer(
            t("fuel_tank_capacity_exceeded", lang, capacity=fmt(capacity, " gal"))
        )
        return
    fuel = data["fuel"]
    # The UI asks for fuel at takeoff, not ramp fuel. Therefore no taxi subtraction is applied
    # and the duplicate ramp/takeoff presentation is collapsed later. The domain field remains
    # available for future integrations that provide an actual ramp quantity and taxi burn.
    fuel[station_id] = {"starting_gal": str(gal), "taxi_burn_gal": "0"}
    await state.update_data(fuel=fuel)
    await push_checkpoint(state, ("fuel", index, "starting"))
    await _render_fuel_prompt(message, state, user, index, "enroute")


@router.callback_query(
    FlightWizard.fuel_starting, F.data == "flight:full_fuel"
)
async def use_full_fuel(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    data = await state.get_data()
    station_id = data["fuel_station_ids"][data["fuel_index"]]
    capacity = Decimal(data["fuel_station_capacities"][station_id])
    await callback.answer()
    await _store_starting_fuel_and_advance(
        callback.message, state, user, capacity
    )


@router.callback_query(
    FlightWizard.fuel_starting, F.data == "flight:use_last_fuel"
)
async def use_last_fuel(
    callback: CallbackQuery, state: FSMContext, user: User
) -> None:
    data = await state.get_data()
    station_id = data["fuel_station_ids"][data["fuel_index"]]
    last_value = data.get("last_fuel_starting", {}).get(station_id)
    if last_value is None:
        await callback.answer()
        return
    await callback.answer()
    await _store_starting_fuel_and_advance(
        callback.message, state, user, Decimal(last_value)
    )


@router.callback_query(FlightWizard.fuel_starting, F.data == "wizard:skip")
async def zero_fuel_starting(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    data = await state.get_data()
    fuel_ids = data["fuel_station_ids"]
    index = data["fuel_index"]
    fuel = data["fuel"]
    fuel[fuel_ids[index]] = {
        "starting_gal": "0",
        "taxi_burn_gal": "0",
    }
    await state.update_data(fuel=fuel)
    await push_checkpoint(state, ("fuel", index, "starting"))
    await callback.answer()
    await _render_fuel_prompt(callback.message, state, user, index, "enroute")


async def _store_fuel_field_and_advance(
    message: Message,
    state: FSMContext,
    user: User,
    checkpoint_field: str,
    data_field: str,
    value: str,
    *,
    landing_fuel_provided: bool,
) -> None:
    data = await state.get_data()
    fuel_ids = data["fuel_station_ids"]
    index = data["fuel_index"]
    fuel = data["fuel"]
    fuel[fuel_ids[index]][data_field] = value
    fuel[fuel_ids[index]]["landing_fuel_provided"] = landing_fuel_provided
    await state.update_data(fuel=fuel)
    await push_checkpoint(state, ("fuel", index, checkpoint_field))

    if checkpoint_field == "enroute":
        await _ask_next_fuel_starting(message, state, user, index + 1)


@router.message(FlightWizard.fuel_enroute, F.text)
async def got_fuel_enroute(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        gal = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    station_id = data["fuel_station_ids"][data["fuel_index"]]
    starting = Decimal(data["fuel"][station_id]["starting_gal"])
    if gal > starting:
        await message.answer(
            t("fuel_burn_exceeded", lang, available=fmt(starting, " gal"))
        )
        return
    await _store_fuel_field_and_advance(
        message,
        state,
        user,
        "enroute",
        "enroute_burn_gal",
        str(gal),
        landing_fuel_provided=True,
    )


@router.callback_query(FlightWizard.fuel_enroute, F.data == "wizard:skip")
async def skip_fuel_enroute(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _store_fuel_field_and_advance(
        callback.message,
        state,
        user,
        "enroute",
        "enroute_burn_gal",
        "0",
        landing_fuel_provided=False,
    )


async def _show_flight_review(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    lines = [t("review_flight_inputs", lang), ""]
    for station_id, weight in data["loads"].items():
        name = data.get("non_fuel_station_names", {}).get(station_id, station_id)
        arm = data.get("load_arms", {}).get(station_id)
        arm_text = f" @ {arm} in" if arm is not None else ""
        lines.append(f"{name}: {weight} lb{arm_text}")
    for station_id, fuel_data in data["fuel"].items():
        name = data.get("fuel_station_names", {}).get(station_id, station_id)
        lines.append(
            f"{name}: start {fuel_data.get('starting_gal', '0')} gal, "
            f"enroute burn {fuel_data.get('enroute_burn_gal', '0')} gal"
        )
    await state.set_state(FlightWizard.review)
    await message.answer("\n".join(lines), reply_markup=confirm_keyboard(lang))


def _phase_text(phase: PhaseResult, lang: str) -> str:
    phase_name = t(f"phase_{phase.phase.lower()}", lang)
    phase_status_key = {
        LimitStatus.WITHIN: "phase_status_within",
        LimitStatus.ON_LIMIT: "phase_status_on_limit",
        LimitStatus.OUT_OF_LIMITS: "phase_status_out_of_limits",
    }[phase.overall_status]
    lines = [f"{phase_name} — {t(phase_status_key, lang)}"]
    lines.append(t("result_weight", lang, value=fmt(phase.total_weight_lb, " lb")))
    if phase.weight_limit_lb is not None:
        limit_key = {
            "RAMP": "result_max_ramp_weight",
            "TAKEOFF": "result_max_takeoff_weight",
            "LANDING": "result_max_landing_weight",
        }[phase.phase]
        lines.append(t(limit_key, lang, value=fmt(phase.weight_limit_lb, " lb")))
        margin = phase.weight_margin_lb
        if margin > 0:
            lines.append(t("result_weight_below", lang, value=fmt(margin, " lb")))
        elif margin < 0:
            lines.append(t("result_weight_over", lang, value=fmt(abs(margin), " lb")))
        else:
            lines.append(t("result_weight_on_limit", lang))
    else:
        lines.append(t("result_weight_limit_not_saved", lang, phase=phase_name))
    lines.append("")
    lines.append(t("result_cg", lang, value=fmt(phase.cg_in, " in")))
    cg = phase.cg_check
    if cg is not None and not cg.weight_within_envelope:
        lines.append(t("result_cg_envelope_not_defined", lang))
    elif cg is not None:
        lines.append(
            t(
                "result_allowed_cg",
                lang,
                forward=fmt(cg.forward_limit_in, " in"),
                aft=fmt(cg.aft_limit_in, " in"),
            )
        )
        if cg.forward_margin_in < 0:
            lines.append(
                t(
                    "result_cg_forward_exceeded",
                    lang,
                    value=fmt(abs(cg.forward_margin_in), " in"),
                )
            )
        elif cg.aft_margin_in < 0:
            lines.append(
                t(
                    "result_cg_aft_exceeded",
                    lang,
                    value=fmt(abs(cg.aft_margin_in), " in"),
                )
            )
        elif cg.status == LimitStatus.ON_LIMIT:
            lines.append(t("result_cg_on_limit", lang))
        else:
            lines.append(t("result_cg_within", lang))
    else:
        lines.append(t("result_cg_not_evaluated", lang))
    for s in phase.station_results:
        if s.over_station_limit:
            lines.append(t("result_station_limit_exceeded", lang, station=s.name))
        if s.over_capacity:
            lines.append(t("result_tank_capacity_exceeded", lang, station=s.name))
    return "\n".join(lines)


def _phase_failure_reasons(phase: PhaseResult, lang: str) -> list[str]:
    phase_name = t(f"phase_{phase.phase.lower()}", lang)
    reasons = []
    if phase.weight_status == LimitStatus.OUT_OF_LIMITS and phase.weight_margin_lb is not None:
        reasons.append(
            t(
                "overall_reason_weight",
                lang,
                phase=phase_name,
                value=fmt(abs(phase.weight_margin_lb), " lb"),
            )
        )
    cg = phase.cg_check
    if cg is not None and not cg.weight_within_envelope:
        reasons.append(t("overall_reason_cg_weight", lang, phase=phase_name))
    elif cg is not None and cg.forward_margin_in < 0:
        reasons.append(
            t(
                "overall_reason_forward_cg",
                lang,
                phase=phase_name,
                value=fmt(abs(cg.forward_margin_in), " in"),
            )
        )
    elif cg is not None and cg.aft_margin_in < 0:
        reasons.append(
            t(
                "overall_reason_aft_cg",
                lang,
                phase=phase_name,
                value=fmt(abs(cg.aft_margin_in), " in"),
            )
        )
    for station in phase.station_results:
        if station.over_station_limit:
            reasons.append(
                t(
                    "overall_reason_station",
                    lang,
                    phase=phase_name,
                    station=station.name,
                )
            )
        if station.over_capacity:
            reasons.append(
                t(
                    "overall_reason_tank",
                    lang,
                    phase=phase_name,
                    station=station.name,
                )
            )
    return reasons


def _status_header(
    result: CalculationResult, lang: str, *, cg_evaluated: bool = True
) -> str:
    header = t(_STATUS_KEY[result.overall_status], lang)
    if not cg_evaluated:
        if result.overall_status == LimitStatus.WITHIN:
            return "⚠️ CG LIMITS NOT EVALUATED — ENTERED WEIGHT LIMITS WITHIN"
        if result.overall_status == LimitStatus.ON_LIMIT:
            return "⚠️ CG LIMITS NOT EVALUATED — ENTERED WEIGHT LIMIT ON BOUNDARY"
        header += " — CG LIMITS NOT EVALUATED"
    return header


def _overall_result_text(result: CalculationResult, lang: str) -> str:
    lines = [t("overall_result", lang)]
    if result.overall_status == LimitStatus.WITHIN:
        lines.append(t("overall_within", lang))
        return "\n".join(lines)
    if result.overall_status == LimitStatus.ON_LIMIT:
        lines.append(t("overall_on_limit", lang))
        return "\n".join(lines)

    reasons = []
    phases = [result.takeoff]
    if result.ramp.total_weight_lb != result.takeoff.total_weight_lb:
        phases.insert(0, result.ramp)
    if result.landing is not None:
        phases.append(result.landing)
    for phase in phases:
        reasons.extend(_phase_failure_reasons(phase, lang))
    if result.zero_fuel_status == LimitStatus.OUT_OF_LIMITS:
        reasons.append(
            t(
                "overall_reason_zfw",
                lang,
                value=fmt(result.zero_fuel_weight_lb - result.zero_fuel_limit_lb, " lb"),
            )
        )
    # The same station or zero-fuel violation can be present in multiple phases. Keep the
    # pilot summary compact while preserving the first, phase-specific occurrence.
    reasons = list(dict.fromkeys(reasons))
    lines.append(t("overall_out_of_limits", lang))
    lines.extend(f"• {reason}" for reason in reasons)
    lines.append(t("overall_adjust_and_recalculate", lang))
    return "\n".join(lines)


_STATUS_KEY = {
    LimitStatus.WITHIN: "status_within",
    LimitStatus.ON_LIMIT: "status_on_limit",
    LimitStatus.OUT_OF_LIMITS: "status_out_of_limits",
}


def _recommendation_text(recs: list[Recommendation], lang: str) -> str:
    if not recs:
        return t("no_recommendations", lang)
    lines = [t("recommendations_header", lang)]
    for i, rec in enumerate(recs, start=1):
        lines.append(f"{i}. {rec.describe()}")
        if rec.note:
            lines.append(f"   {rec.note}")
    return "\n".join(lines)


@router.callback_query(FlightWizard.review, F.data == "wizard:confirm")
async def flight_review_confirm(
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
        await callback.message.answer(t("aircraft_profile_invalid", lang, detail=str(exc)))
        await callback.answer()
        return
    if aircraft is None or profile is None:
        await callback.answer(t("no_aircraft_selected", lang), show_alert=True)
        await state.clear()
        return

    loads = [
        LoadItemInput(
            station_id=sid,
            weight_lb=Decimal(weight),
            arm_in=(
                Decimal(data.get("load_arms", {})[sid])
                if sid in data.get("load_arms", {})
                else None
            ),
        )
        for sid, weight in data["loads"].items()
    ]
    fuel = [
        FuelStationInput(
            station_id=sid,
            starting_gal=Decimal(fdata.get("starting_gal", "0")),
            taxi_burn_gal=Decimal(fdata.get("taxi_burn_gal", "0")),
            enroute_burn_gal=Decimal(fdata.get("enroute_burn_gal", "0")),
            landing_fuel_provided=bool(fdata.get("landing_fuel_provided", False)),
        )
        for sid, fdata in data["fuel"].items()
    ]

    calc_input = CalculationInput(loads=loads, fuel=fuel)

    try:
        result = flight_service.run_calculation(profile, calc_input)
    except DomainError as exc:
        await callback.message.answer(t("error_generic", lang, detail=str(exc)))
        await callback.answer()
        return

    await flight_service.persist_calculation(
        user_id=user.id,
        aircraft_id=aircraft.id,
        aircraft_revision_id=aircraft.active_revision_id,
        calc_input=calc_input,
        result=result,
    )

    # The overall status always reflects the actual current/takeoff (and landing, if
    # evaluated) result -- "landing not evaluated" is noted separately below, it must never
    # replace or hide a real WITHIN/ON_LIMIT/OUT_OF_LIMITS finding with a fake "incomplete".
    lines = [
        _status_header(result, lang, cg_evaluated=profile.envelope is not None),
        "",
    ]
    lines.append(profile.tail_number)
    lines.append("")
    if profile.envelope is None:
        lines.append("⚠️ No CG envelope on file -- weight checked, CG NOT evaluated.")
        lines.append("")
    if result.zero_fuel_limit_lb is not None:
        zfw_margin = result.zero_fuel_limit_lb - result.zero_fuel_weight_lb
        zfw_word = "margin" if zfw_margin >= 0 else "over limit"
        lines.append(
            f"ZERO-FUEL WEIGHT: {fmt(result.zero_fuel_weight_lb, ' lb')} / "
            f"{fmt(result.zero_fuel_limit_lb, ' lb')} "
            f"({fmt(abs(zfw_margin), ' lb')} {zfw_word})"
        )
        lines.append("")
    ramp_and_takeoff_identical = result.ramp.total_weight_lb == result.takeoff.total_weight_lb
    if ramp_and_takeoff_identical:
        lines.append(_phase_text(result.takeoff, lang))
    else:
        lines.append(_phase_text(result.ramp, lang))
        lines.append("")
        lines.append(_phase_text(result.takeoff, lang))
    lines.append("")
    if result.landing is not None:
        lines.append(_phase_text(result.landing, lang))
        lines.append("")
    elif not result.landing_evaluated:
        lines.append(t("landing_not_evaluated", lang))
        lines.append("")
    lines.append(_overall_result_text(result, lang))
    lines.append("")
    lines.append(t("result_footer", lang))

    await state.clear()

    if result.overall_status != LimitStatus.OUT_OF_LIMITS:
        # ON LIMIT is a valid boundary result, not a request to change the loading.
        await callback.message.answer("\n".join(lines), reply_markup=main_menu_keyboard(lang))
    else:
        await callback.message.answer("\n".join(lines))
        recs = flight_service.recommend(profile, calc_input)
        await callback.message.answer(
            _recommendation_text(recs, lang), reply_markup=main_menu_keyboard(lang)
        )

    await callback.answer()


def _history_summary(calc) -> str:
    """Pulls a compact weight/status summary out of either engine's result snapshot --
    the quick-calculate result and the full ramp/takeoff/landing result have different
    shapes, so both are handled defensively rather than assuming one format."""
    try:
        result = json.loads(calc.result_snapshot_json)
    except (ValueError, TypeError):
        return "status unavailable"
    if not isinstance(result, dict):
        # Older builds accidentally stored dataclasses as opaque strings. Keep history usable
        # instead of crashing while those legacy records remain in the database.
        return "legacy result — details unavailable"

    status = result.get("overall_status", "?")
    weight = None
    if "total_weight_lb" in result:
        weight = result["total_weight_lb"]
    elif isinstance(result.get("takeoff"), dict):
        weight = result["takeoff"].get("total_weight_lb")

    try:
        weight_text = f"{Decimal(str(weight)):,.1f} lb" if weight is not None else "? lb"
    except (ArithmeticError, ValueError):
        weight_text = "? lb"
    status_text = {
        "WITHIN": "Within Limits",
        "ON_LIMIT": "On Limit",
        "OUT_OF_LIMITS": "OUT",
    }.get(status, status)
    return f"{weight_text} -- {status_text}"


@router.message(F.text.in_({t("menu_history", "en"), t("menu_history", "ru")}))
async def calculation_history(
    message: Message,
    state: FSMContext,
    user: User,
    flight_service: FlightService,
    aircraft_service: AircraftService,
) -> None:
    await state.clear()
    lang = _lang(user)
    history = await flight_service.list_history(user.id, limit=10)
    if not history:
        await message.answer(t("history_empty", lang))
        return

    aircraft_cache: dict[int, str] = {}
    lines = []
    for calc in history:
        if calc.aircraft_id not in aircraft_cache:
            aircraft = await aircraft_service.get_aircraft(user.id, calc.aircraft_id)
            aircraft_cache[calc.aircraft_id] = aircraft.tail_number if aircraft else "?"
        tail = aircraft_cache[calc.aircraft_id]
        lines.append(f"{calc.created_at:%b %d} -- {tail} -- {_history_summary(calc)}")
    await message.answer("\n".join(lines))


@router.callback_query(FlightWizard.review, F.data == "wizard:edit")
async def flight_review_edit(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
    flight_service: FlightService,
) -> None:
    data = await state.get_data()
    seed_values = {
        "loads": dict(data.get("loads", {})),
        "load_arms": dict(data.get("load_arms", {})),
        "fuel_starting": {
            station_id: values["starting_gal"]
            for station_id, values in data.get("fuel", {}).items()
            if "starting_gal" in values
        },
    }
    await callback.answer()
    await _begin_for_aircraft(
        callback.message,
        state,
        user,
        aircraft_service,
        flight_service,
        data["aircraft_id"],
        seed_values=seed_values,
    )


@router.message(StateFilter(FlightWizard))
async def unsupported_flight_message(message: Message, user: User) -> None:
    await message.answer(t("unsupported_wizard_message", _lang(user)))
