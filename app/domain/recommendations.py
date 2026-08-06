"""Deterministic recommendation solver for the Advanced per-station calculation.

Every candidate is applied to a copy of the input and run through the complete calculator before
it is returned. Moves are searched within `_MOVABLE_GROUPS`: a seat pair (Front <-> Rear) or
Rear Seats <-> Baggage (rear-seat cargo relocation) -- Rear Seats participates in both groups,
Front Seats never trades directly with Baggage, and no move ever touches an ambiguous CUSTOM
station. Seat-to-seat suggestions are phrased as a plain weight shift ("Move X lb from Front
Seats to Rear Seats") without asserting who moves -- the app has no way to know who is sitting
where, so it leaves that call to the pilot.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.config import settings
from app.domain.calculator import calculate
from app.domain.envelope import LimitStatus
from app.domain.exceptions import DomainError
from app.domain.models import (
    AircraftProfile,
    CalculationInput,
    FuelStationInput,
    LoadItemInput,
    StationProfile,
    StationType,
)
from app.domain.units import compact_decimal, lb_to_kg

FUEL_STEP_GAL = Decimal("0.1")
LOAD_STEP_LB = Decimal("1")
MAX_STEPS = 5000

_FUEL_RESERVE_NOTE = (
    "Confirm the resulting fuel still meets your planned trip and legal reserve requirements."
)


class RecommendationKind(str, Enum):
    REDUCE_FUEL = "REDUCE_FUEL"
    ADD_FUEL = "ADD_FUEL"
    REDUCE_BAGGAGE = "REDUCE_BAGGAGE"
    ADD_BAGGAGE = "ADD_BAGGAGE"
    REDUCE_SEAT_LOAD = "REDUCE_SEAT_LOAD"
    MOVE_LOAD = "MOVE_LOAD"
    SHIFT_FUEL = "SHIFT_FUEL"
    COMBINATION = "COMBINATION"


@dataclass(frozen=True)
class Recommendation:
    kind: RecommendationKind
    station_id: str
    station_name: str
    delta_lb: Decimal | None = None
    delta_gal: Decimal | None = None
    target_station_id: str | None = None
    target_station_name: str | None = None
    note: str | None = None
    resulting_gal: Decimal | None = None
    tank_capacity_gal: Decimal | None = None
    legs: tuple["Recommendation", ...] | None = None
    resulting_takeoff_cg_in: Decimal | None = None

    def describe(self) -> str:
        def display(value: Decimal) -> str:
            return compact_decimal(value, decimal_places=1)

        if self.kind == RecommendationKind.REDUCE_FUEL:
            text = (
                f"Reduce fuel in {self.station_name} by {display(self.delta_gal)} US gal "
                f"({display(self.delta_lb)} lb)."
            )
            if self.resulting_gal is not None:
                text += f" Target level: {display(self.resulting_gal)} gal."
        elif self.kind == RecommendationKind.ADD_FUEL:
            text = (
                f"Add fuel to {self.station_name}: +{display(self.delta_gal)} US gal "
                f"(+{display(self.delta_lb)} lb)."
            )
            if self.resulting_gal is not None:
                if (
                    self.tank_capacity_gal is not None
                    and self.resulting_gal >= self.tank_capacity_gal
                ):
                    text += (
                        f" Target level: fill to full ({display(self.resulting_gal)} gal)."
                    )
                else:
                    text += f" Target level: {display(self.resulting_gal)} gal."
        elif self.kind in (RecommendationKind.REDUCE_BAGGAGE, RecommendationKind.REDUCE_SEAT_LOAD):
            kg = lb_to_kg(self.delta_lb)
            text = (
                f"Remove {display(self.delta_lb)} lb ({display(kg)} kg) from "
                f"{self.station_name}."
            )
        elif self.kind == RecommendationKind.ADD_BAGGAGE:
            kg = lb_to_kg(self.delta_lb)
            text = (
                f"Add {display(self.delta_lb)} lb ({display(kg)} kg) to "
                f"{self.station_name}."
            )
        elif self.kind == RecommendationKind.MOVE_LOAD:
            kg = lb_to_kg(self.delta_lb)
            text = (
                f"Move {display(self.delta_lb)} lb ({display(kg)} kg) from {self.station_name} "
                f"to {self.target_station_name}."
            )
        elif self.kind == RecommendationKind.SHIFT_FUEL:
            text = (
                f"Transfer {display(self.delta_gal)} US gal of fuel from {self.station_name} "
                f"to {self.target_station_name} (total fuel unchanged)."
            )
        elif self.kind == RecommendationKind.COMBINATION:
            text = " AND ".join(leg.describe() for leg in self.legs)
        else:
            text = "Adjustment."

        # Same-amount suggestions targeting different stations (e.g. two tanks with different
        # ARMs both needing the same weight cut) look identical without this -- the resulting CG
        # is where their difference actually shows up, so it's surfaced on every suggestion
        # rather than only when a look-alike happens to be nearby.
        if self.resulting_takeoff_cg_in is not None:
            text += f" Resulting takeoff CG: {display(self.resulting_takeoff_cg_in)} in."
        return text


def _is_acceptable(status: LimitStatus) -> bool:
    return status != LimitStatus.OUT_OF_LIMITS


def _try_calculate(profile: AircraftProfile, calc_input: CalculationInput):
    """Reject expected invalid candidates; let programming errors surface."""
    try:
        return calculate(profile, calc_input)
    except DomainError:
        return None


def _replace_fuel(
    calc_input: CalculationInput, station_id: str, new_starting_gal: Decimal
) -> CalculationInput:
    found = False
    new_fuel = []
    for fuel in calc_input.fuel:
        if fuel.station_id == station_id:
            new_fuel.append(dataclasses.replace(fuel, starting_gal=new_starting_gal))
            found = True
        else:
            new_fuel.append(fuel)
    if not found:
        raise ValueError(f"Fuel station '{station_id}' is absent from calculation input")
    return dataclasses.replace(calc_input, fuel=new_fuel)


def _reduce_fuel_floor_gal(fuel: FuelStationInput, external_floor: Decimal) -> Decimal:
    """A tank can never be loaded below its own taxi burn -- that fuel is spent on the ground
    before the CG condition being calculated even applies. Taxi burn is therefore a hard floor
    in addition to whatever minimum the pilot/caller supplied."""
    return max(external_floor, fuel.taxi_burn_gal)


def _replace_fuel_reducing(
    calc_input: CalculationInput, station_id: str, new_starting_gal: Decimal
) -> CalculationInput:
    """Like `_replace_fuel`, but for a *reduction*: also caps enroute burn down to whatever the
    lower starting quantity can actually supply. Without this, loading less into a tank that was
    planned to be flown dry (enroute burn == starting fuel, common for an AUX/tip tank that feeds
    into the main tank rather than the engine) makes taxi+enroute burn exceed the new starting
    fuel, which the calculator correctly treats as an invalid input -- silently making that tank
    look infeasible to reduce, when the real fix is simply to plan on burning less from it too."""
    found = False
    new_fuel = []
    for fuel in calc_input.fuel:
        if fuel.station_id == station_id:
            capped_enroute = min(
                fuel.enroute_burn_gal, max(Decimal("0"), new_starting_gal - fuel.taxi_burn_gal)
            )
            new_fuel.append(
                dataclasses.replace(
                    fuel, starting_gal=new_starting_gal, enroute_burn_gal=capped_enroute
                )
            )
            found = True
        else:
            new_fuel.append(fuel)
    if not found:
        raise ValueError(f"Fuel station '{station_id}' is absent from calculation input")
    return dataclasses.replace(calc_input, fuel=new_fuel)


def _replace_load(
    calc_input: CalculationInput, station_id: str, new_weight: Decimal
) -> CalculationInput:
    found = False
    new_loads = []
    for load in calc_input.loads:
        if load.station_id == station_id:
            new_loads.append(dataclasses.replace(load, weight_lb=new_weight))
            found = True
        else:
            new_loads.append(load)
    if not found:
        new_loads.append(LoadItemInput(station_id=station_id, weight_lb=new_weight))
    return dataclasses.replace(calc_input, loads=new_loads)


def _current_load_weight(calc_input: CalculationInput, station_id: str) -> Decimal:
    for load in calc_input.loads:
        if load.station_id == station_id:
            return load.weight_lb
    return Decimal("0")


def _apply_combination_leg(
    calc_input: CalculationInput, leg: Recommendation, amount: Decimal
) -> CalculationInput:
    """Apply `amount` (a fraction of `leg`'s full delta) of a single-category leg on top of
    calc_input. Fuel-side and load-side legs never touch the same station, so applying one
    leg's partial amount, then the other's, on the same base input is always safe."""
    if leg.kind == RecommendationKind.REDUCE_FUEL:
        current = next(f.starting_gal for f in calc_input.fuel if f.station_id == leg.station_id)
        return _replace_fuel_reducing(calc_input, leg.station_id, current - amount)
    if leg.kind == RecommendationKind.ADD_FUEL:
        current = next(f.starting_gal for f in calc_input.fuel if f.station_id == leg.station_id)
        return _replace_fuel(calc_input, leg.station_id, current + amount)
    if leg.kind == RecommendationKind.SHIFT_FUEL:
        source = next(f.starting_gal for f in calc_input.fuel if f.station_id == leg.station_id)
        dest = next(
            f.starting_gal for f in calc_input.fuel if f.station_id == leg.target_station_id
        )
        candidate = _replace_fuel_reducing(calc_input, leg.station_id, source - amount)
        return _replace_fuel(candidate, leg.target_station_id, dest + amount)
    if leg.kind in (RecommendationKind.REDUCE_BAGGAGE, RecommendationKind.REDUCE_SEAT_LOAD):
        current = _current_load_weight(calc_input, leg.station_id)
        return _replace_load(calc_input, leg.station_id, current - amount)
    if leg.kind == RecommendationKind.ADD_BAGGAGE:
        current = _current_load_weight(calc_input, leg.station_id)
        return _replace_load(calc_input, leg.station_id, current + amount)
    if leg.kind == RecommendationKind.MOVE_LOAD:
        source_w = _current_load_weight(calc_input, leg.station_id)
        dest_w = _current_load_weight(calc_input, leg.target_station_id)
        candidate = _replace_load(calc_input, leg.station_id, source_w - amount)
        return _replace_load(candidate, leg.target_station_id, dest_w + amount)
    raise ValueError(f"Cannot apply combination leg of kind {leg.kind}")


def _leg_magnitude(leg: Recommendation) -> Decimal:
    return leg.delta_gal if leg.delta_gal is not None else leg.delta_lb


def _leg_step(leg: Recommendation) -> Decimal:
    return FUEL_STEP_GAL if leg.delta_gal is not None else LOAD_STEP_LB


def _half_step_amount(alone: Decimal, step: Decimal) -> Decimal:
    steps_count = max(1, int((alone / 2) / step))
    return step * steps_count


def _leg_with_amount(profile: AircraftProfile, leg: Recommendation, amount: Decimal) -> Recommendation:
    """The combination search scales a leg down to a partial amount, so any resulting-CG value
    carried over from that leg's own full alone-fix (or absent, for a ceiling-only leg) no longer
    describes this smaller amount -- only the combination's own top-level result does."""
    if leg.delta_gal is not None:
        station = profile.station(leg.station_id)
        return dataclasses.replace(
            leg, delta_gal=amount, delta_lb=amount * station.fuel_density_lb_per_gal,
            resulting_gal=None, resulting_takeoff_cg_in=None,
        )
    return dataclasses.replace(leg, delta_lb=amount, resulting_takeoff_cg_in=None)


# Moves are only ever searched within one of these groups -- never between them, and never
# touching an ambiguous CUSTOM station (could be equipment, a fixed installation, or movable
# cargo -- no way to tell automatically).
_MOVABLE_GROUPS = (
    {StationType.FRONT_SEATS, StationType.REAR_SEATS},   # seat swap
    {StationType.REAR_SEATS, StationType.BAGGAGE},       # rear-seat cargo <-> baggage
)


def _search_move_load(
    profile: AircraftProfile, calc_input: CalculationInput
) -> list[Recommendation]:
    """Suggest shifting weight within one of `_MOVABLE_GROUPS`: a seat pair (Front <-> Rear)
    or Rear Seats <-> Baggage (rear-seat cargo relocation) -- Rear Seats participates in both
    groups, Front Seats never trades directly with Baggage.

    Seat-to-seat suggestions are phrased as a plain weight shift ("Move X lb from Front Seats
    to Rear Seats") -- the app has no way to know who is sitting where, so it never names a
    specific occupant or asserts who should move.
    """
    results: list[Recommendation] = []
    for group in _MOVABLE_GROUPS:
        movable = [station for station in profile.stations if station.station_type in group]
        for source in movable:
            source_weight = _current_load_weight(calc_input, source.station_id)
            if source_weight <= 0:
                continue
            for destination in movable:
                if destination.station_id == source.station_id:
                    continue
                destination_weight = _current_load_weight(calc_input, destination.station_id)
                headroom = source_weight
                if headroom <= 0:
                    continue
                steps = min(int(headroom / LOAD_STEP_LB), MAX_STEPS)
                for step in range(1, steps + 1):
                    delta = LOAD_STEP_LB * step
                    candidate = _replace_load(
                        calc_input, source.station_id, source_weight - delta
                    )
                    candidate = _replace_load(
                        candidate, destination.station_id, destination_weight + delta
                    )
                    result = _try_calculate(profile, candidate)
                    if result and _is_acceptable(result.overall_status):
                        results.append(
                            Recommendation(
                                kind=RecommendationKind.MOVE_LOAD,
                                station_id=source.station_id,
                                station_name=source.name,
                                target_station_id=destination.station_id,
                                target_station_name=destination.name,
                                delta_lb=delta,
                                resulting_takeoff_cg_in=result.takeoff.cg_in,
                            )
                        )
                        break
    return results


def _search_reduce_baggage(
    profile: AircraftProfile, calc_input: CalculationInput
) -> list[Recommendation]:
    results: list[Recommendation] = []
    for station in profile.baggage_stations:
        current = _current_load_weight(calc_input, station.station_id)
        if current <= 0:
            continue
        steps = min(int(current / LOAD_STEP_LB), MAX_STEPS)
        for step in range(1, steps + 1):
            delta = LOAD_STEP_LB * step
            candidate = _replace_load(calc_input, station.station_id, current - delta)
            result = _try_calculate(profile, candidate)
            if result and _is_acceptable(result.overall_status):
                results.append(
                    Recommendation(
                        kind=RecommendationKind.REDUCE_BAGGAGE,
                        station_id=station.station_id,
                        station_name=station.name,
                        delta_lb=delta,
                        resulting_takeoff_cg_in=result.takeoff.cg_in,
                    )
                )
                break
    return results


_SEAT_STATION_TYPES = {StationType.FRONT_SEATS, StationType.REAR_SEATS}


def _seat_floor_lb(station: StationProfile) -> Decimal:
    """Front Seats always needs at least a pilot aboard; Rear Seats has no minimum."""
    if station.station_type == StationType.FRONT_SEATS:
        return Decimal(str(settings.min_front_seat_weight_lb))
    return Decimal("0")


def _search_reduce_seat_load(
    profile: AircraftProfile, calc_input: CalculationInput
) -> list[Recommendation]:
    results: list[Recommendation] = []
    for station in profile.stations:
        if station.station_type not in _SEAT_STATION_TYPES:
            continue
        current = _current_load_weight(calc_input, station.station_id)
        floor = _seat_floor_lb(station)
        if current <= floor:
            continue
        steps = min(int((current - floor) / LOAD_STEP_LB), MAX_STEPS)
        for step in range(1, steps + 1):
            delta = LOAD_STEP_LB * step
            target = current - delta
            if target < floor:
                break
            candidate = _replace_load(calc_input, station.station_id, target)
            result = _try_calculate(profile, candidate)
            if result and _is_acceptable(result.overall_status):
                results.append(
                    Recommendation(
                        kind=RecommendationKind.REDUCE_SEAT_LOAD,
                        station_id=station.station_id,
                        station_name=station.name,
                        delta_lb=delta,
                        resulting_takeoff_cg_in=result.takeoff.cg_in,
                    )
                )
                break
    return results


def _search_add_baggage(
    profile: AircraftProfile, calc_input: CalculationInput
) -> list[Recommendation]:
    """Suggest adding baggage aft, which can correct a forward CG (or a large weight margin).

    There's no per-station published limit to bound against anymore, so headroom is bounded by
    the aircraft's maximum takeoff weight instead, computed from the current loading.
    """
    baseline = _try_calculate(profile, calc_input)
    if baseline is None:
        return []
    headroom = profile.max_takeoff_weight_lb - baseline.takeoff.total_weight_lb
    if headroom <= 0:
        return []
    results: list[Recommendation] = []
    steps = min(int(headroom / LOAD_STEP_LB), MAX_STEPS)
    for station in profile.baggage_stations:
        current = _current_load_weight(calc_input, station.station_id)
        for step in range(1, steps + 1):
            delta = LOAD_STEP_LB * step
            candidate = _replace_load(calc_input, station.station_id, current + delta)
            result = _try_calculate(profile, candidate)
            if result and _is_acceptable(result.overall_status):
                results.append(
                    Recommendation(
                        kind=RecommendationKind.ADD_BAGGAGE,
                        station_id=station.station_id,
                        station_name=station.name,
                        delta_lb=delta,
                        resulting_takeoff_cg_in=result.takeoff.cg_in,
                    )
                )
                break
    return results


def _search_reduce_fuel(
    profile: AircraftProfile,
    calc_input: CalculationInput,
    min_fuel_gal: dict[str, Decimal],
) -> list[Recommendation]:
    results: list[Recommendation] = []
    for fuel in calc_input.fuel:
        floor = _reduce_fuel_floor_gal(fuel, min_fuel_gal.get(fuel.station_id, Decimal("0")))
        if fuel.starting_gal <= floor:
            continue
        station = profile.station(fuel.station_id)
        steps = min(int((fuel.starting_gal - floor) / FUEL_STEP_GAL), MAX_STEPS)
        for step in range(1, steps + 1):
            delta_gal = FUEL_STEP_GAL * step
            target = fuel.starting_gal - delta_gal
            if target < floor:
                break
            candidate = _replace_fuel_reducing(calc_input, fuel.station_id, target)
            result = _try_calculate(profile, candidate)
            if result and _is_acceptable(result.overall_status):
                results.append(
                    Recommendation(
                        kind=RecommendationKind.REDUCE_FUEL,
                        station_id=station.station_id,
                        station_name=station.name,
                        delta_lb=delta_gal * station.fuel_density_lb_per_gal,
                        delta_gal=delta_gal,
                        resulting_gal=target,
                        tank_capacity_gal=station.maximum_volume_gal,
                        note=_FUEL_RESERVE_NOTE,
                        resulting_takeoff_cg_in=result.takeoff.cg_in,
                    )
                )
                break
    return results


def _search_shift_fuel(
    profile: AircraftProfile,
    calc_input: CalculationInput,
    min_fuel_gal: dict[str, Decimal],
) -> list[Recommendation]:
    """Optional only: actual fuel transfer must be permitted by the aircraft fuel system."""
    results: list[Recommendation] = []
    for source in calc_input.fuel:
        floor = _reduce_fuel_floor_gal(source, min_fuel_gal.get(source.station_id, Decimal("0")))
        if source.starting_gal <= floor:
            continue
        source_station = profile.station(source.station_id)
        for destination in calc_input.fuel:
            if destination.station_id == source.station_id:
                continue
            destination_station = profile.station(destination.station_id)
            headroom = min(
                source.starting_gal - floor,
                destination_station.maximum_volume_gal - destination.starting_gal,
            )
            if headroom <= 0:
                continue
            steps = min(int(headroom / FUEL_STEP_GAL), MAX_STEPS)
            for step in range(1, steps + 1):
                delta = FUEL_STEP_GAL * step
                candidate = _replace_fuel_reducing(
                    calc_input, source.station_id, source.starting_gal - delta
                )
                candidate = _replace_fuel(
                    candidate,
                    destination.station_id,
                    destination.starting_gal + delta,
                )
                result = _try_calculate(profile, candidate)
                if result and _is_acceptable(result.overall_status):
                    results.append(
                        Recommendation(
                            kind=RecommendationKind.SHIFT_FUEL,
                            station_id=source.station_id,
                            station_name=source_station.name,
                            target_station_id=destination.station_id,
                            target_station_name=destination_station.name,
                            delta_gal=delta,
                            note=(
                                "Use only if this transfer is permitted by the aircraft fuel-system "
                                "documents and can be performed as described."
                            ),
                            resulting_takeoff_cg_in=result.takeoff.cg_in,
                        )
                    )
                    break
    return results


def _search_add_fuel(
    profile: AircraftProfile, calc_input: CalculationInput
) -> list[Recommendation]:
    results: list[Recommendation] = []
    for fuel in calc_input.fuel:
        station = profile.station(fuel.station_id)
        headroom = station.maximum_volume_gal - fuel.starting_gal
        if headroom <= 0:
            continue
        steps = min(int(headroom / FUEL_STEP_GAL), MAX_STEPS)
        for step in range(1, steps + 1):
            delta_gal = FUEL_STEP_GAL * step
            target = fuel.starting_gal + delta_gal
            candidate = _replace_fuel(calc_input, fuel.station_id, target)
            result = _try_calculate(profile, candidate)
            if result and _is_acceptable(result.overall_status):
                results.append(
                    Recommendation(
                        kind=RecommendationKind.ADD_FUEL,
                        station_id=station.station_id,
                        station_name=station.name,
                        delta_lb=delta_gal * station.fuel_density_lb_per_gal,
                        delta_gal=delta_gal,
                        resulting_gal=target,
                        tank_capacity_gal=station.maximum_volume_gal,
                        resulting_takeoff_cg_in=result.takeoff.cg_in,
                    )
                )
                break
    return results


_CATEGORY_PRIORITY = {
    RecommendationKind.MOVE_LOAD: 0,
    RecommendationKind.REDUCE_SEAT_LOAD: 1,
    RecommendationKind.REDUCE_BAGGAGE: 2,
    RecommendationKind.ADD_BAGGAGE: 3,
    RecommendationKind.SHIFT_FUEL: 4,
    RecommendationKind.ADD_FUEL: 5,
    RecommendationKind.REDUCE_FUEL: 6,
}

MAX_COMBO_ATTEMPTS = 200

_COMBINATION_FUEL_KINDS = (
    RecommendationKind.REDUCE_FUEL, RecommendationKind.ADD_FUEL, RecommendationKind.SHIFT_FUEL,
)
_COMBINATION_LOAD_KINDS = (
    RecommendationKind.MOVE_LOAD, RecommendationKind.REDUCE_SEAT_LOAD,
    RecommendationKind.REDUCE_BAGGAGE, RecommendationKind.ADD_BAGGAGE,
)


def _verified_key(recommendation: Recommendation) -> tuple[RecommendationKind, str]:
    return (recommendation.kind, recommendation.station_id)


def _reduce_fuel_ceiling_legs(
    profile: AircraftProfile,
    calc_input: CalculationInput,
    min_fuel_gal: dict[str, Decimal],
    exclude_station_ids: set[str],
) -> list[Recommendation]:
    """Structural (unverified) full-range REDUCE_FUEL legs, for combination search only.

    `_search_reduce_fuel` only reports a station when draining it *alone* already fixes the
    violation. But a station whose own maximum possible reduction still isn't enough by itself
    can be exactly what's needed once paired with a load-side leg (e.g. a large charter/overload
    case needing more than any single station can fix alone) -- so the combination search gets
    each remaining station's full headroom to work with, without asserting that headroom alone
    is a working fix. Stations already covered by a verified alone-fix are excluded; that
    stronger result is used instead."""
    legs: list[Recommendation] = []
    for fuel in calc_input.fuel:
        if fuel.station_id in exclude_station_ids:
            continue
        floor = _reduce_fuel_floor_gal(fuel, min_fuel_gal.get(fuel.station_id, Decimal("0")))
        if fuel.starting_gal <= floor:
            continue
        station = profile.station(fuel.station_id)
        delta_gal = fuel.starting_gal - floor
        legs.append(
            Recommendation(
                kind=RecommendationKind.REDUCE_FUEL,
                station_id=station.station_id,
                station_name=station.name,
                delta_lb=delta_gal * station.fuel_density_lb_per_gal,
                delta_gal=delta_gal,
                tank_capacity_gal=station.maximum_volume_gal,
                note=_FUEL_RESERVE_NOTE,
            )
        )
    return legs


def _reduce_seat_ceiling_legs(
    profile: AircraftProfile, calc_input: CalculationInput, exclude_station_ids: set[str]
) -> list[Recommendation]:
    """Structural (unverified) full-range REDUCE_SEAT_LOAD legs -- see
    `_reduce_fuel_ceiling_legs` for why the combination search needs these alongside the
    verified alone-fix search."""
    legs: list[Recommendation] = []
    for station in profile.stations:
        if station.station_type not in _SEAT_STATION_TYPES or station.station_id in exclude_station_ids:
            continue
        current = _current_load_weight(calc_input, station.station_id)
        floor = _seat_floor_lb(station)
        if current <= floor:
            continue
        legs.append(
            Recommendation(
                kind=RecommendationKind.REDUCE_SEAT_LOAD,
                station_id=station.station_id,
                station_name=station.name,
                delta_lb=current - floor,
            )
        )
    return legs


def _reduce_baggage_ceiling_legs(
    profile: AircraftProfile, calc_input: CalculationInput, exclude_station_ids: set[str]
) -> list[Recommendation]:
    """Structural (unverified) full-range REDUCE_BAGGAGE legs -- see
    `_reduce_fuel_ceiling_legs` for why the combination search needs these alongside the
    verified alone-fix search."""
    legs: list[Recommendation] = []
    for station in profile.baggage_stations:
        if station.station_id in exclude_station_ids:
            continue
        current = _current_load_weight(calc_input, station.station_id)
        if current <= 0:
            continue
        legs.append(
            Recommendation(
                kind=RecommendationKind.REDUCE_BAGGAGE,
                station_id=station.station_id,
                station_name=station.name,
                delta_lb=current,
            )
        )
    return legs


def _search_combinations(
    profile: AircraftProfile,
    calc_input: CalculationInput,
    fuel_side: list[Recommendation],
    load_side: list[Recommendation],
    verified: set[tuple[RecommendationKind, str]],
) -> list[Recommendation]:
    results: list[Recommendation] = []
    for fuel_leg in fuel_side:
        if fuel_leg.kind not in _COMBINATION_FUEL_KINDS:
            continue
        fuel_alone = _leg_magnitude(fuel_leg)
        fuel_step = _leg_step(fuel_leg)
        fuel_verified = _verified_key(fuel_leg) in verified
        for load_leg in load_side:
            if load_leg.kind not in _COMBINATION_LOAD_KINDS:
                continue
            load_alone = _leg_magnitude(load_leg)
            load_step = _leg_step(load_leg)
            load_verified = _verified_key(load_leg) in verified

            fuel_amount = _half_step_amount(fuel_alone, fuel_step)
            load_amount = _half_step_amount(load_alone, load_step)
            grow_fuel_next = fuel_amount <= load_amount
            found_amounts = None
            for _ in range(MAX_COMBO_ATTEMPTS):
                if fuel_amount > fuel_alone or load_amount > load_alone:
                    break
                candidate = _apply_combination_leg(calc_input, fuel_leg, fuel_amount)
                candidate = _apply_combination_leg(candidate, load_leg, load_amount)
                result = _try_calculate(profile, candidate)
                if result and _is_acceptable(result.overall_status):
                    found_amounts = (fuel_amount, load_amount)
                    break
                if grow_fuel_next:
                    fuel_amount += fuel_step
                else:
                    load_amount += load_step
                grow_fuel_next = not grow_fuel_next

            if found_amounts is None:
                continue
            fuel_amount, load_amount = found_amounts
            # A leg with no verified alone-fix (its own maximum wasn't enough by itself) has no
            # standalone suggestion to be compared against, so a combination using it is always
            # new information. Only when a leg *is* verified do we require the combination to
            # improve on that leg's own already-offered alone amount -- otherwise the combo is
            # strictly no better than the simpler single-category suggestion that already exists.
            if fuel_verified and load_verified:
                not_worth_it = fuel_amount >= fuel_alone and load_amount >= load_alone
            elif fuel_verified:
                not_worth_it = fuel_amount >= fuel_alone
            elif load_verified:
                not_worth_it = load_amount >= load_alone
            else:
                not_worth_it = False
            if not_worth_it:
                continue
            fuel_result_leg = _leg_with_amount(profile, fuel_leg, fuel_amount)
            load_result_leg = _leg_with_amount(profile, load_leg, load_amount)
            # A leg's `note` (e.g. SHIFT_FUEL's fuel-system safety disclaimer) is preserved on
            # the leg itself, but `Recommendation.describe()` for COMBINATION only joins each
            # leg's `describe()` text and callers typically read `.note` off the top-level
            # object -- surface it there too so it's never silently dropped.
            note = next(
                (leg.note for leg in (fuel_result_leg, load_result_leg) if leg.note), None
            )
            results.append(
                Recommendation(
                    kind=RecommendationKind.COMBINATION,
                    station_id=fuel_leg.station_id,
                    station_name=fuel_leg.station_name,
                    note=note,
                    legs=(fuel_result_leg, load_result_leg),
                    resulting_takeoff_cg_in=result.takeoff.cg_in,
                )
            )
    return results


def _combination_priority(recommendation: Recommendation) -> int:
    if recommendation.kind == RecommendationKind.COMBINATION and recommendation.legs:
        fuel_leg = recommendation.legs[0]
        return _CATEGORY_PRIORITY.get(fuel_leg.kind, 99)
    return _CATEGORY_PRIORITY.get(recommendation.kind, 99)


def _tiebreak(recommendation: Recommendation) -> Decimal:
    if recommendation.kind == RecommendationKind.COMBINATION and recommendation.legs:
        return sum((leg.delta_lb for leg in recommendation.legs), Decimal("0"))
    if recommendation.delta_lb is not None:
        return recommendation.delta_lb
    if recommendation.delta_gal is not None:
        return recommendation.delta_gal
    return Decimal("0")


def _reduce_fuel_arm_tiebreak(recommendation: Recommendation, profile: AircraftProfile) -> Decimal:
    """When two REDUCE_FUEL candidates need an equal (or near-equal) cut, prefer draining the
    tank with the larger ARM first. A tank far from the datum is the one most aircraft fuel
    systems treat as auxiliary/supplemental (feeding into a tank closer to the datum rather than
    the engine directly), so it's the one a pilot can actually leave under-filled -- unlike the
    near-datum tank, which is usually the one the fuel system keeps full. `_tiebreak` above still
    decides first whenever the required cut actually differs between tanks."""
    if recommendation.kind == RecommendationKind.COMBINATION and recommendation.legs:
        leg = recommendation.legs[0]
    else:
        leg = recommendation
    if leg.kind != RecommendationKind.REDUCE_FUEL:
        return Decimal("0")
    return -profile.station(leg.station_id).default_arm_in


def generate_recommendations(
    profile: AircraftProfile,
    calc_input: CalculationInput,
    min_fuel_gal: dict[str, Decimal] | None = None,
    max_results: int = 4,
    *,
    allow_fuel_transfer: bool = False,
    allow_add_fuel: bool = False,
) -> list[Recommendation]:
    """Return verified load adjustments in practical priority order.

    The standard UI does not ask for a minimum-fuel value. Consequently, every fuel-reduction
    recommendation includes an explicit reminder that trip/reserve requirements remain the
    pilot's responsibility. Callers that already know a hard floor may still pass it here.
    """
    min_fuel_gal = min_fuel_gal or {}

    move_load_results = _search_move_load(profile, calc_input)
    reduce_seat_results = _search_reduce_seat_load(profile, calc_input)
    reduce_baggage_results = _search_reduce_baggage(profile, calc_input)
    add_baggage_results = _search_add_baggage(profile, calc_input)
    reduce_fuel_results = _search_reduce_fuel(profile, calc_input, min_fuel_gal)
    shift_fuel_results = (
        _search_shift_fuel(profile, calc_input, min_fuel_gal) if allow_fuel_transfer else []
    )
    add_fuel_results = _search_add_fuel(profile, calc_input) if allow_add_fuel else []

    candidates: list[Recommendation] = []
    candidates += move_load_results
    candidates += reduce_seat_results
    candidates += reduce_baggage_results
    candidates += add_baggage_results
    candidates += reduce_fuel_results
    candidates += shift_fuel_results
    candidates += add_fuel_results

    # A station whose own maximum possible reduction still doesn't fix the violation alone (so
    # it never made it into the verified results above) can still be exactly what's needed once
    # paired with another leg -- e.g. a full-aircraft overload that needs more than any single
    # tank or seat can fix by itself. These ceiling-only legs give the combination search each
    # remaining station's full headroom without claiming that headroom alone is a working fix.
    verified = {_verified_key(recommendation) for recommendation in candidates}
    reduce_fuel_ceiling = _reduce_fuel_ceiling_legs(
        profile, calc_input, min_fuel_gal, {r.station_id for r in reduce_fuel_results}
    )
    reduce_seat_ceiling = _reduce_seat_ceiling_legs(
        profile, calc_input, {r.station_id for r in reduce_seat_results}
    )
    reduce_baggage_ceiling = _reduce_baggage_ceiling_legs(
        profile, calc_input, {r.station_id for r in reduce_baggage_results}
    )

    load_side_results = (
        move_load_results
        + reduce_seat_results + reduce_seat_ceiling
        + reduce_baggage_results + reduce_baggage_ceiling
        + add_baggage_results
    )
    fuel_side_results = (
        reduce_fuel_results + reduce_fuel_ceiling + shift_fuel_results + add_fuel_results
    )
    candidates += _search_combinations(
        profile, calc_input, fuel_side_results, load_side_results, verified
    )

    candidates.sort(
        key=lambda recommendation: (
            _combination_priority(recommendation),
            _tiebreak(recommendation),
            _reduce_fuel_arm_tiebreak(recommendation, profile),
        )
    )
    return candidates[:max_results]
