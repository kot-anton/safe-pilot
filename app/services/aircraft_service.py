"""Bridges Telegram-facing wizard data <-> persistent storage <-> the pure domain model.

Aircraft updates always create a new AircraftRevision; historical revisions (and the
FlightCalculations that used them) are never mutated.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from app.database.models import Aircraft, AircraftRevision, StationTypeEnum
from app.domain.envelope import CGEnvelope, EnvelopeRow
from app.domain.exceptions import InconsistentAircraftDataError
from app.domain.models import (
    AircraftProfile,
    StationProfile,
    StationType,
    station_type_order,
)
from app.repositories.aircraft_repository import AircraftRepository

USEFUL_LOAD_TOLERANCE_LB = Decimal("5.0")
EMPTY_CG_CONSISTENCY_TOLERANCE_IN = Decimal("0.01")


@dataclass(frozen=True)
class StationDraft:
    name: str
    station_type: StationType
    default_arm_in: Decimal
    is_adjustable_arm: bool = False
    minimum_arm_in: Decimal | None = None
    maximum_arm_in: Decimal | None = None
    maximum_weight_lb: Decimal | None = None
    maximum_volume_gal: Decimal | None = None
    fuel_density_lb_per_gal: Decimal | None = None


@dataclass(frozen=True)
class EnvelopeRowDraft:
    weight_lb: Decimal
    forward_cg_limit_in: Decimal
    aft_cg_limit_in: Decimal


@dataclass(frozen=True)
class AircraftRevisionDraft:
    basic_empty_weight_lb: Decimal
    basic_empty_moment_lb_in: Decimal
    basic_empty_cg_in: Decimal
    max_takeoff_weight_lb: Decimal
    stations: list[StationDraft]
    envelope_rows: list[EnvelopeRowDraft]
    max_ramp_weight_lb: Decimal | None = None
    max_landing_weight_lb: Decimal | None = None
    max_zero_fuel_weight_lb: Decimal | None = None
    known_useful_load_lb: Decimal | None = None
    source_document_name: str | None = None
    source_document_date: datetime.date | None = None
    notes: str | None = None


def _require_finite(value: Decimal, label: str) -> None:
    if not value.is_finite():
        raise InconsistentAircraftDataError(f"{label} must be finite")


def empty_moment_from_cg(weight_lb: Decimal, cg_in: Decimal) -> Decimal:
    _require_finite(weight_lb, "Basic Empty Weight")
    _require_finite(cg_in, "Basic Empty CG")
    if weight_lb <= 0:
        raise InconsistentAircraftDataError("Basic Empty Weight must be greater than zero")
    return weight_lb * cg_in


def empty_cg_from_moment(weight_lb: Decimal, moment_lb_in: Decimal) -> Decimal:
    _require_finite(weight_lb, "Basic Empty Weight")
    _require_finite(moment_lb_in, "Basic Empty Moment")
    if weight_lb <= 0:
        raise InconsistentAircraftDataError("Basic Empty Weight must be greater than zero")
    return moment_lb_in / weight_lb


def validate_aircraft_identity(
    tail_number: str, model: str, nickname: str | None, manufacturer: str | None
) -> None:
    tail = tail_number.strip()
    model_name = model.strip()
    if not tail:
        raise InconsistentAircraftDataError("Aircraft tail number or identifier is required")
    if len(tail) > 16:
        raise InconsistentAircraftDataError("Aircraft identifier must be 16 characters or fewer")
    if not model_name:
        raise InconsistentAircraftDataError("Aircraft model is required")
    if len(model_name) > 64:
        raise InconsistentAircraftDataError("Aircraft model must be 64 characters or fewer")
    if nickname is not None and len(nickname.strip()) > 64:
        raise InconsistentAircraftDataError("Aircraft nickname must be 64 characters or fewer")
    if manufacturer is not None and len(manufacturer.strip()) > 64:
        raise InconsistentAircraftDataError("Manufacturer must be 64 characters or fewer")


def validate_revision_draft(draft: "AircraftRevisionDraft") -> None:
    """Validate a complete revision before any database write occurs.

    This prevents invalid/partial revisions and, during aircraft creation, prevents an orphan
    aircraft row if the station or envelope data is malformed.
    """
    for label, value in (
        ("Basic Empty Weight", draft.basic_empty_weight_lb),
        ("Basic Empty Moment", draft.basic_empty_moment_lb_in),
        ("Basic Empty CG", draft.basic_empty_cg_in),
        ("Maximum Takeoff Weight", draft.max_takeoff_weight_lb),
    ):
        _require_finite(value, label)

    calculated_cg = empty_cg_from_moment(
        draft.basic_empty_weight_lb, draft.basic_empty_moment_lb_in
    )
    if abs(calculated_cg - draft.basic_empty_cg_in) > EMPTY_CG_CONSISTENCY_TOLERANCE_IN:
        raise InconsistentAircraftDataError(
            "Basic Empty Weight, Moment, and CG are inconsistent: "
            f"Moment / Weight gives {calculated_cg:.4f} in, but CG is "
            f"{draft.basic_empty_cg_in:.4f} in"
        )

    if draft.known_useful_load_lb is not None:
        _require_finite(draft.known_useful_load_lb, "Known Useful Load")
        if draft.known_useful_load_lb < 0:
            raise InconsistentAircraftDataError("Known Useful Load cannot be negative")

    if draft.source_document_name is not None and len(draft.source_document_name.strip()) > 128:
        raise InconsistentAircraftDataError("Source document name must be 128 characters or fewer")

    station_profiles = [
        StationProfile(
            station_id=f"draft-{index}",
            name=station.name.strip(),
            station_type=station.station_type,
            default_arm_in=station.default_arm_in,
            is_adjustable_arm=station.is_adjustable_arm,
            minimum_arm_in=station.minimum_arm_in,
            maximum_arm_in=station.maximum_arm_in,
            maximum_weight_lb=station.maximum_weight_lb,
            maximum_volume_gal=station.maximum_volume_gal,
            fuel_density_lb_per_gal=station.fuel_density_lb_per_gal,
        )
        for index, station in enumerate(draft.stations)
    ]
    for station in draft.stations:
        if len(station.name.strip()) > 64:
            raise InconsistentAircraftDataError(
                f"Station name '{station.name}' must be 64 characters or fewer"
            )

    if draft.envelope_rows:
        envelope = CGEnvelope(
            [
                EnvelopeRow(
                    row.weight_lb, row.forward_cg_limit_in, row.aft_cg_limit_in
                )
                for row in draft.envelope_rows
            ]
        )
    else:
        envelope = None

    # AircraftProfile performs the remaining cross-field limit validation.
    AircraftProfile(
        tail_number="DRAFT",
        revision_number=1,
        basic_empty_weight_lb=draft.basic_empty_weight_lb,
        basic_empty_moment_lb_in=draft.basic_empty_moment_lb_in,
        max_takeoff_weight_lb=draft.max_takeoff_weight_lb,
        stations=station_profiles,
        envelope=envelope,
        max_ramp_weight_lb=draft.max_ramp_weight_lb,
        max_landing_weight_lb=draft.max_landing_weight_lb,
        max_zero_fuel_weight_lb=draft.max_zero_fuel_weight_lb,
    )


def useful_load_warning(draft: AircraftRevisionDraft) -> str | None:
    """Returns a warning message if the pilot-entered known useful load disagrees with the
    calculated value beyond tolerance. Useful load is never used to derive CG."""
    if draft.known_useful_load_lb is None:
        return None
    calculated = draft.max_takeoff_weight_lb - draft.basic_empty_weight_lb
    diff = abs(calculated - draft.known_useful_load_lb)
    if diff > USEFUL_LOAD_TOLERANCE_LB:
        return (
            f"Entered known useful load ({draft.known_useful_load_lb} lb) differs from the "
            f"calculated takeoff useful load ({calculated} lb) by {diff} lb, which exceeds the "
            f"configured tolerance ({USEFUL_LOAD_TOLERANCE_LB} lb). Please double-check your entries."
        )
    return None


class AircraftService:
    def __init__(self, repo: AircraftRepository):
        self.repo = repo

    async def get_or_create_user(self, telegram_user_id: int, language: str = "en"):
        return await self.repo.get_or_create_user(telegram_user_id, language)

    async def list_aircraft(self, user_id: int) -> list[Aircraft]:
        return await self.repo.list_aircraft(user_id)

    async def get_aircraft(self, user_id: int, aircraft_id: int) -> Aircraft | None:
        return await self.repo.get_aircraft(user_id, aircraft_id)

    async def create_aircraft(
        self,
        user_id: int,
        tail_number: str,
        model: str,
        nickname: str | None,
        manufacturer: str | None,
        draft: AircraftRevisionDraft,
        is_temporary: bool = False,
    ) -> Aircraft:
        validate_aircraft_identity(tail_number, model, nickname, manufacturer)
        validate_revision_draft(draft)
        aircraft = await self.repo.create_aircraft(
            user_id, tail_number, model, nickname, manufacturer, is_temporary
        )
        await self._add_revision(aircraft, draft)
        # A newly created aircraft becomes the active one automatically -- no separate
        # "Select Aircraft" step required before the pilot can calculate with it.
        await self.repo.set_selected_aircraft_id(user_id, aircraft.id)
        return aircraft

    async def update_aircraft(self, aircraft: Aircraft, draft: AircraftRevisionDraft) -> AircraftRevision:
        validate_revision_draft(draft)
        return await self._add_revision(aircraft, draft)

    async def _add_revision(self, aircraft: Aircraft, draft: AircraftRevisionDraft) -> AircraftRevision:
        ordered_stations = sorted(
            draft.stations,
            key=lambda station: station_type_order(station.station_type),
        )
        stations = [
            {
                "name": s.name,
                "station_type": StationTypeEnum(s.station_type.value),
                "default_arm_in": s.default_arm_in,
                "is_adjustable_arm": s.is_adjustable_arm,
                "minimum_arm_in": s.minimum_arm_in,
                "maximum_arm_in": s.maximum_arm_in,
                "maximum_weight_lb": s.maximum_weight_lb,
                "maximum_volume_gal": s.maximum_volume_gal,
                "fuel_density_lb_per_gal": s.fuel_density_lb_per_gal,
                "active": True,
            }
            for s in ordered_stations
        ]
        envelope_rows = [
            {
                "weight_lb": r.weight_lb,
                "forward_cg_limit_in": r.forward_cg_limit_in,
                "aft_cg_limit_in": r.aft_cg_limit_in,
            }
            for r in draft.envelope_rows
        ]
        return await self.repo.add_revision(
            aircraft,
            basic_empty_weight_lb=draft.basic_empty_weight_lb,
            basic_empty_moment_lb_in=draft.basic_empty_moment_lb_in,
            basic_empty_cg_in=draft.basic_empty_cg_in,
            max_ramp_weight_lb=draft.max_ramp_weight_lb,
            max_takeoff_weight_lb=draft.max_takeoff_weight_lb,
            max_landing_weight_lb=draft.max_landing_weight_lb,
            max_zero_fuel_weight_lb=draft.max_zero_fuel_weight_lb,
            known_useful_load_lb=draft.known_useful_load_lb,
            source_document_name=draft.source_document_name,
            source_document_date=draft.source_document_date,
            notes=draft.notes,
            stations=stations,
            envelope_rows=envelope_rows,
        )

    async def archive_aircraft(self, aircraft: Aircraft) -> None:
        await self.repo.archive_aircraft(aircraft)

    async def select_aircraft(self, user, aircraft_id: int | None) -> None:
        await self.repo.set_selected_aircraft(user, aircraft_id)

    async def get_revision_for_user(self, user_id: int, revision_id: int) -> AircraftRevision | None:
        return await self.repo.get_revision(user_id, revision_id)



def suspicious_non_fuel_stations(profile: AircraftProfile) -> list[StationProfile]:
    """Return stations that look like fuel tanks but are not configured as FUEL.

    This is intentionally a warning-only heuristic: it never mutates or reclassifies aviation
    data. It catches the historical failure mode where a station named "Fuel Aux Tanks" was
    stored as CUSTOM and then requested in pounds.
    """
    suspicious: list[StationProfile] = []
    for station in profile.stations:
        if station.station_type == StationType.FUEL:
            continue
        words = {word.strip("-_/()[]") for word in station.name.casefold().split()}
        if "fuel" in words or "tank" in words or "tanks" in words:
            suspicious.append(station)
    return suspicious

def build_domain_profile(revision: AircraftRevision, aircraft: Aircraft) -> AircraftProfile:
    """Converts a persisted AircraftRevision into the pure domain AircraftProfile."""
    stations = [
        StationProfile(
            station_id=str(s.id),
            name=s.name,
            station_type=StationType(s.station_type.value),
            default_arm_in=s.default_arm_in,
            is_adjustable_arm=s.is_adjustable_arm,
            minimum_arm_in=s.minimum_arm_in,
            maximum_arm_in=s.maximum_arm_in,
            maximum_weight_lb=s.maximum_weight_lb,
            maximum_volume_gal=s.maximum_volume_gal,
            fuel_density_lb_per_gal=s.fuel_density_lb_per_gal,
        )
        for s in revision.stations
        if s.active
    ]
    sorted_envelope_rows = sorted(revision.envelope_rows, key=lambda r: r.weight_lb)
    # An aircraft may have no CG envelope on file (explicitly skipped during setup) --
    # CG is then simply not evaluated rather than assumed safe.
    envelope = (
        CGEnvelope(
            [
                EnvelopeRow(
                    weight_lb=r.weight_lb,
                    forward_cg_limit_in=r.forward_cg_limit_in,
                    aft_cg_limit_in=r.aft_cg_limit_in,
                )
                for r in sorted_envelope_rows
            ]
        )
        if len(sorted_envelope_rows) >= 2
        else None
    )
    return AircraftProfile(
        tail_number=aircraft.tail_number,
        revision_number=revision.revision_number,
        basic_empty_weight_lb=revision.basic_empty_weight_lb,
        basic_empty_moment_lb_in=revision.basic_empty_moment_lb_in,
        max_takeoff_weight_lb=revision.max_takeoff_weight_lb,
        stations=stations,
        envelope=envelope,
        max_ramp_weight_lb=revision.max_ramp_weight_lb,
        max_landing_weight_lb=revision.max_landing_weight_lb,
        max_zero_fuel_weight_lb=revision.max_zero_fuel_weight_lb,
    )
