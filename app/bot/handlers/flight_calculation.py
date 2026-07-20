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

from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message

from app.bot.handlers._common import InputParseError, fmt, parse_decimal, parse_optional_decimal
from app.bot.handlers.wizard_nav import pop_checkpoint, push_checkpoint
from app.bot.keyboards.common import aircraft_list_keyboard, confirm_keyboard, main_menu_keyboard, skip_cancel_keyboard
from app.bot.states.flight_wizard import FlightWizard
from app.bot.texts.i18n import t
from app.database.models import User
from app.domain.envelope import LimitStatus
from app.domain.models import CalculationInput, FuelStationInput, LoadItemInput, PhaseResult, StationType
from app.domain.recommendations import Recommendation
from app.services.aircraft_service import AircraftService
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


@router.message(F.text.in_({t("menu_new_calc", "en"), t("menu_new_calc", "ru")}))
async def start_calculation(
    message: Message, state: FSMContext, user: User, aircraft_service: AircraftService
) -> None:
    lang = _lang(user)
    await state.clear()
    if user.selected_aircraft_id:
        await _begin_for_aircraft(message, state, user, aircraft_service, user.selected_aircraft_id)
        return
    aircraft_list = await aircraft_service.list_aircraft(user.id)
    if not aircraft_list:
        await message.answer(t("no_aircraft_yet", lang))
        return
    await state.set_state(FlightWizard.select_aircraft)
    await message.answer(
        t("select_aircraft_prompt", lang), reply_markup=aircraft_list_keyboard(aircraft_list, "calc_select")
    )


@router.callback_query(FlightWizard.select_aircraft, F.data.startswith("calc_select:"))
async def calc_select_aircraft(
    callback: CallbackQuery, state: FSMContext, user: User, aircraft_service: AircraftService
) -> None:
    aircraft_id = int(callback.data.split(":")[1])
    await _begin_for_aircraft(callback.message, state, user, aircraft_service, aircraft_id)
    await callback.answer()


async def _begin_for_aircraft(
    message: Message, state: FSMContext, user: User, aircraft_service: AircraftService, aircraft_id: int
) -> None:
    lang = _lang(user)
    aircraft, profile = await _load_profile_and_aircraft(user.id, aircraft_id, aircraft_service)
    if aircraft is None or profile is None:
        await message.answer(t("no_aircraft_selected", lang))
        return

    non_fuel_stations = [s for s in profile.stations if s.station_type != StationType.FUEL]
    fuel_stations = profile.fuel_stations

    await state.update_data(
        aircraft_id=aircraft.id,
        revision_number=profile.revision_number,
        tail_number=profile.tail_number,
        non_fuel_station_ids=[s.station_id for s in non_fuel_stations],
        non_fuel_station_names={s.station_id: s.name for s in non_fuel_stations},
        fuel_station_ids=[s.station_id for s in fuel_stations],
        fuel_station_names={s.station_id: s.name for s in fuel_stations},
        load_index=0,
        fuel_index=0,
        loads={},
        fuel={},
        _nav_history=[],
    )
    banner = f"{t('unverified_banner', lang)}\n\n{profile.tail_number} -- rev. {profile.revision_number}"
    await message.answer(banner)

    if not non_fuel_stations:
        await _ask_next_fuel_starting(message, state, user)
        return

    await _render_load_prompt(message, state, user, 0, show_back=False)


async def _render_load_prompt(message: Message, state: FSMContext, user: User, index: int, *, show_back: bool = True) -> None:
    await state.update_data(load_index=index)
    await state.set_state(FlightWizard.load_at_station)
    data = await state.get_data()
    lang = _lang(user)
    station_ids = data["non_fuel_station_ids"]
    name = data.get("non_fuel_station_names", {}).get(station_ids[index], station_ids[index])
    await message.answer(
        t("ask_load_at_station", lang, station=name), reply_markup=skip_cancel_keyboard(lang, show_back=show_back)
    )


_FUEL_FIELD_STATE: dict[str, tuple[State, str]] = {
    "starting": (FlightWizard.fuel_starting, "ask_fuel_starting"),
    "taxi": (FlightWizard.fuel_taxi, "ask_fuel_taxi"),
    "enroute": (FlightWizard.fuel_enroute, "ask_fuel_enroute"),
    "minimum": (FlightWizard.fuel_minimum, "ask_min_fuel"),
}


async def _render_fuel_prompt(message: Message, state: FSMContext, user: User, index: int, field: str) -> None:
    await state.update_data(fuel_index=index)
    target_state, text_key = _FUEL_FIELD_STATE[field]
    await state.set_state(target_state)
    data = await state.get_data()
    lang = _lang(user)
    fuel_ids = data["fuel_station_ids"]
    name = data.get("fuel_station_names", {}).get(fuel_ids[index], fuel_ids[index])
    await message.answer(t(text_key, lang, station=name), reply_markup=skip_cancel_keyboard(lang))


async def _cannot_go_back(callback: CallbackQuery) -> None:
    await callback.answer("Already at the first step.")


@router.callback_query(StateFilter(FlightWizard), F.data == "wizard:back")
async def flight_back(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    checkpoint = await pop_checkpoint(state)
    if checkpoint is None:
        await _cannot_go_back(callback)
        return
    kind = checkpoint[0]
    if kind == "load":
        await _render_load_prompt(callback.message, state, user, checkpoint[1])
    else:
        await _render_fuel_prompt(callback.message, state, user, checkpoint[1], checkpoint[2])
    await callback.answer()


@router.message(FlightWizard.load_at_station)
async def got_load_at_station(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        weight = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    station_ids = data["non_fuel_station_ids"]
    index = data["load_index"]
    loads = data["loads"]
    loads[station_ids[index]] = str(weight)
    await state.update_data(loads=loads)
    await push_checkpoint(state, ("load", index))
    await _ask_next_load_or_fuel(message, state, user, index + 1)


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
    loads[station_ids[index]] = "0"
    await state.update_data(loads=loads)
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


@router.message(FlightWizard.fuel_starting)
async def got_fuel_starting(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        gal = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    data = await state.get_data()
    fuel_ids = data["fuel_station_ids"]
    index = data["fuel_index"]
    fuel = data["fuel"]
    fuel[fuel_ids[index]] = {"starting_gal": str(gal)}
    await state.update_data(fuel=fuel)
    await push_checkpoint(state, ("fuel", index, "starting"))
    await _render_fuel_prompt(message, state, user, index, "taxi")


@router.message(FlightWizard.fuel_taxi)
async def got_fuel_taxi(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        gal = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await _store_fuel_field_and_advance(message, state, user, "taxi", "taxi_burn_gal", str(gal))


@router.callback_query(FlightWizard.fuel_taxi, F.data == "wizard:skip")
async def skip_fuel_taxi(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _store_fuel_field_and_advance(callback.message, state, user, "taxi", "taxi_burn_gal", "0")


async def _store_fuel_field_and_advance(
    message: Message, state: FSMContext, user: User, checkpoint_field: str, data_field: str, value: str
) -> None:
    data = await state.get_data()
    fuel_ids = data["fuel_station_ids"]
    index = data["fuel_index"]
    fuel = data["fuel"]
    fuel[fuel_ids[index]][data_field] = value
    await state.update_data(fuel=fuel)
    await push_checkpoint(state, ("fuel", index, checkpoint_field))

    if checkpoint_field == "taxi":
        await _render_fuel_prompt(message, state, user, index, "enroute")
    elif checkpoint_field == "enroute":
        await _render_fuel_prompt(message, state, user, index, "minimum")
    elif checkpoint_field == "minimum":
        await _ask_next_fuel_starting(message, state, user, index + 1)


@router.message(FlightWizard.fuel_enroute)
async def got_fuel_enroute(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        gal = parse_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await _store_fuel_field_and_advance(message, state, user, "enroute", "enroute_burn_gal", str(gal))


@router.callback_query(FlightWizard.fuel_enroute, F.data == "wizard:skip")
async def skip_fuel_enroute(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _store_fuel_field_and_advance(callback.message, state, user, "enroute", "enroute_burn_gal", "0")


@router.message(FlightWizard.fuel_minimum)
async def got_fuel_minimum(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    try:
        gal = parse_optional_decimal(message.text)
    except InputParseError as exc:
        await message.answer(t("error_generic", lang, detail=str(exc)))
        return
    await _store_fuel_field_and_advance(
        message, state, user, "minimum", "min_fuel_gal", str(gal) if gal is not None else ""
    )


@router.callback_query(FlightWizard.fuel_minimum, F.data == "wizard:skip")
async def skip_fuel_minimum(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    await callback.answer()
    await _store_fuel_field_and_advance(callback.message, state, user, "minimum", "min_fuel_gal", "")


async def _show_flight_review(message: Message, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    data = await state.get_data()
    lines = [t("review_flight_inputs", lang), ""]
    for station_id, weight in data["loads"].items():
        name = data.get("non_fuel_station_names", {}).get(station_id, station_id)
        lines.append(f"{name}: {weight} lb")
    for station_id, fuel_data in data["fuel"].items():
        name = data.get("fuel_station_names", {}).get(station_id, station_id)
        lines.append(
            f"{name}: start {fuel_data.get('starting_gal', '0')} gal, "
            f"taxi burn {fuel_data.get('taxi_burn_gal', '0')} gal, "
            f"enroute burn {fuel_data.get('enroute_burn_gal', '0')} gal"
        )
    await state.set_state(FlightWizard.review)
    await message.answer("\n".join(lines), reply_markup=confirm_keyboard(lang))


def _phase_text(phase: PhaseResult, lang: str) -> str:
    lines = [phase.phase]
    lines.append(f"Weight: {fmt(phase.total_weight_lb, ' lb')}")
    if phase.weight_limit_lb is not None:
        lines.append(f"Limit: {fmt(phase.weight_limit_lb, ' lb')}")
        margin = phase.weight_margin_lb
        lines.append(f"Weight margin: {fmt(margin, ' lb')}")
    lines.append(f"CG: {fmt(phase.cg_in, ' in')}")
    cg = phase.cg_check
    lines.append(f"Allowed: {fmt(cg.forward_limit_in, ' in')}-{fmt(cg.aft_limit_in, ' in')}")
    lines.append(f"Forward margin: {fmt(cg.forward_margin_in, ' in')}")
    lines.append(f"Aft margin: {fmt(cg.aft_margin_in, ' in')}")
    for s in phase.station_results:
        if s.over_station_limit:
            lines.append(f"⚠️ {s.name} exceeds its station weight limit")
        if s.over_capacity:
            lines.append(f"⚠️ {s.name} exceeds fuel tank capacity")
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
    aircraft, profile = await _load_profile_and_aircraft(user.id, data["aircraft_id"], aircraft_service)
    if aircraft is None or profile is None:
        await callback.answer(t("no_aircraft_selected", lang), show_alert=True)
        await state.clear()
        return

    loads = [LoadItemInput(station_id=sid, weight_lb=Decimal(w)) for sid, w in data["loads"].items()]
    fuel = []
    min_fuel_gal: dict[str, Decimal] = {}
    for sid, fdata in data["fuel"].items():
        fuel.append(
            FuelStationInput(
                station_id=sid,
                starting_gal=Decimal(fdata.get("starting_gal", "0")),
                taxi_burn_gal=Decimal(fdata.get("taxi_burn_gal", "0")),
                enroute_burn_gal=Decimal(fdata.get("enroute_burn_gal", "0")),
            )
        )
        min_val = fdata.get("min_fuel_gal")
        if min_val:
            min_fuel_gal[sid] = Decimal(min_val)

    calc_input = CalculationInput(loads=loads, fuel=fuel)

    try:
        result = flight_service.run_calculation(profile, calc_input)
    except Exception as exc:
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

    lines = [t("unverified_banner", lang), ""]
    if not result.landing_evaluated:
        overall_key = "status_incomplete"
    else:
        overall_key = _STATUS_KEY[result.overall_status]
    lines.append(t(overall_key, lang))
    lines.append("")
    lines.append(f"Aircraft: {profile.tail_number}")
    lines.append(f"Profile revision: {profile.revision_number}")
    lines.append("")
    lines.append(_phase_text(result.ramp, lang))
    lines.append("")
    lines.append(_phase_text(result.takeoff, lang))
    lines.append("")
    if result.landing is not None:
        lines.append(_phase_text(result.landing, lang))
    else:
        lines.append(t("landing_not_evaluated", lang))
    lines.append("")
    lines.append(t("disclaimer", lang))

    await callback.message.answer("\n".join(lines))

    if result.overall_status != LimitStatus.WITHIN:
        recs = flight_service.recommend(
            profile,
            calc_input,
            min_fuel_gal=min_fuel_gal,
            allow_added_ballast_recommendations=aircraft.allow_added_ballast_recommendations,
        )
        await callback.message.answer(_recommendation_text(recs, lang))

    await state.clear()
    await callback.message.answer(t("main_menu", lang), reply_markup=main_menu_keyboard(lang))
    await callback.answer()


@router.message(F.text.in_({t("menu_history", "en"), t("menu_history", "ru")}))
async def calculation_history(message: Message, user: User, flight_service: FlightService) -> None:
    lang = _lang(user)
    history = await flight_service.list_history(user.id, limit=10)
    if not history:
        await message.answer(t("history_empty", lang))
        return
    lines = []
    for calc in history:
        lines.append(f"#{calc.id} -- {calc.created_at:%Y-%m-%d %H:%M} UTC (engine {calc.calculation_engine_version})")
    await message.answer("\n".join(lines))


@router.callback_query(FlightWizard.review, F.data == "wizard:edit")
async def flight_review_edit(
    callback: CallbackQuery, state: FSMContext, user: User, aircraft_service: AircraftService
) -> None:
    data = await state.get_data()
    await callback.answer()
    await _begin_for_aircraft(callback.message, state, user, aircraft_service, data["aircraft_id"])
