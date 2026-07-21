"""Entry point into the Update Aircraft flow.

Reuses the AircraftWizard states/handlers from aircraft_wizard.py: the revision's current
values are pre-loaded into FSM data, so every step's "Keep current" button lets the pilot
skip straight through fields they are not changing -- only the field(s) they want to edit
need new input.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.handlers.aircraft_wizard import render_empty_weight
from app.bot.handlers.wizard_nav import goto
from app.bot.keyboards.common import aircraft_list_keyboard
from app.bot.states.aircraft_wizard import AircraftWizard
from app.bot.texts.i18n import t
from app.database.models import User
from app.services.aircraft_service import AircraftService

router = Router(name="aircraft_update")


def _lang(user: User) -> str:
    return user.language or "en"


@router.message(F.text.in_({t("menu_update_aircraft", "en"), t("menu_update_aircraft", "ru")}))
async def update_aircraft_prompt(message: Message, user: User, aircraft_service: AircraftService) -> None:
    lang = _lang(user)
    aircraft_list = await aircraft_service.list_aircraft(user.id)
    if not aircraft_list:
        await message.answer(t("no_aircraft_yet", lang))
        return
    await message.answer(
        t("select_aircraft_prompt", lang), reply_markup=aircraft_list_keyboard(aircraft_list, "update")
    )


@router.callback_query(F.data.startswith("update:"))
async def update_aircraft_chosen(
    callback: CallbackQuery, state: FSMContext, user: User, aircraft_service: AircraftService
) -> None:
    aircraft_id = int(callback.data.split(":")[1])
    aircraft = await aircraft_service.get_aircraft(user.id, aircraft_id)
    if aircraft is None or aircraft.active_revision_id is None:
        await callback.answer()
        return
    revision = await aircraft_service.get_revision_for_user(user.id, aircraft.active_revision_id)
    if revision is None:
        await callback.answer()
        return

    stations = [
        {
            "name": s.name,
            "station_type": s.station_type.value,
            "default_arm_in": str(s.default_arm_in),
            "is_adjustable_arm": s.is_adjustable_arm,
            "minimum_arm_in": str(s.minimum_arm_in) if s.minimum_arm_in is not None else None,
            "maximum_arm_in": str(s.maximum_arm_in) if s.maximum_arm_in is not None else None,
            "maximum_weight_lb": str(s.maximum_weight_lb) if s.maximum_weight_lb is not None else None,
            "maximum_volume_gal": str(s.maximum_volume_gal) if s.maximum_volume_gal is not None else None,
            "fuel_density_lb_per_gal": str(s.fuel_density_lb_per_gal) if s.fuel_density_lb_per_gal is not None else None,
        }
        for s in revision.stations
        if s.active
    ]
    envelope_rows = [
        {
            "weight_lb": str(r.weight_lb),
            "forward_cg_limit_in": str(r.forward_cg_limit_in),
            "aft_cg_limit_in": str(r.aft_cg_limit_in),
        }
        for r in sorted(revision.envelope_rows, key=lambda r: r.weight_lb)
    ]

    await state.clear()
    await state.update_data(
        update_mode=True,
        aircraft_id=aircraft.id,
        tail_number=aircraft.tail_number,
        model=aircraft.model,
        nickname=aircraft.nickname,
        manufacturer=aircraft.manufacturer,
        basic_empty_weight_lb=str(revision.basic_empty_weight_lb),
        basic_empty_cg_in=str(revision.basic_empty_cg_in),
        basic_empty_moment_lb_in=str(revision.basic_empty_moment_lb_in),
        max_ramp_weight_lb=str(revision.max_ramp_weight_lb) if revision.max_ramp_weight_lb is not None else None,
        max_takeoff_weight_lb=str(revision.max_takeoff_weight_lb),
        max_landing_weight_lb=str(revision.max_landing_weight_lb) if revision.max_landing_weight_lb is not None else None,
        max_zero_fuel_weight_lb=str(revision.max_zero_fuel_weight_lb) if revision.max_zero_fuel_weight_lb is not None else None,
        known_useful_load_lb=str(revision.known_useful_load_lb) if revision.known_useful_load_lb is not None else None,
        source_document_name=revision.source_document_name,
        source_document_date=revision.source_document_date.isoformat() if revision.source_document_date else None,
        stations=stations,
        envelope_rows=envelope_rows,
    )
    await callback.message.answer(f"Updating {aircraft.tail_number} (currently rev. {revision.revision_number}).")
    await goto(callback.message, state, user, AircraftWizard.empty_weight, render_empty_weight, record_history=False)
    await callback.answer()
