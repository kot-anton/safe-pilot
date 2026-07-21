"""Deterministic recommendation solver for the Advanced per-station calculation.

Every candidate is applied to a copy of the input and run through the complete calculator before
it is returned. Passenger reseating is deliberately never suggested: this solver only changes
movable cargo/baggage and fuel quantities. Added load is considered only at a baggage station
with an explicit published maximum stored in the aircraft profile.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.domain.calculator import calculate
from app.domain.envelope import LimitStatus
from app.domain.exceptions import DomainError
from app.domain.models import AircraftProfile, CalculationInput, LoadItemInput, StationType
from app.domain.units import lb_to_kg

FUEL_STEP_GAL = Decimal("0.1")
LOAD_STEP_LB = Decimal("1")
MAX_STEPS = 5000

FUEL_REDUCTION_NOTE = (
    "Use only if required trip fuel, reserve fuel, and tank limitations remain satisfied."
)
ADDED_LOAD_NOTE = (
    "Use only permitted load, keep within the published compartment limit, and secure it "
    "in accordance with the aircraft documents."
)


class RecommendationKind(str, Enum):
    REDUCE_FUEL = "REDUCE_FUEL"
    ADD_FUEL = "ADD_FUEL"
    REDUCE_BAGGAGE = "REDUCE_BAGGAGE"
    ADD_BAGGAGE = "ADD_BAGGAGE"
    MOVE_LOAD = "MOVE_LOAD"
    SHIFT_FUEL = "SHIFT_FUEL"


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
    resulting_station_weight_lb: Decimal | None = None

    def describe(self) -> str:
        if self.kind == RecommendationKind.REDUCE_FUEL:
            text = (
                f"Reduce fuel in {self.station_name} by {self.delta_gal:.1f} US gal "
                f"({self.delta_lb:.1f} lb)."
            )
            if self.resulting_gal is not None:
                text += f" Target level: {self.resulting_gal:.1f} gal."
            return text
        if self.kind == RecommendationKind.ADD_FUEL:
            text = (
                f"Add fuel to {self.station_name}: +{self.delta_gal:.1f} US gal "
                f"(+{self.delta_lb:.1f} lb)."
            )
            if self.resulting_gal is not None:
                if (
                    self.tank_capacity_gal is not None
                    and self.resulting_gal >= self.tank_capacity_gal
                ):
                    text += f" Target level: fill to full ({self.resulting_gal:.1f} gal)."
                else:
                    text += f" Target level: {self.resulting_gal:.1f} gal."
            return text
        if self.kind == RecommendationKind.REDUCE_BAGGAGE:
            kg = lb_to_kg(self.delta_lb)
            return (
                f"Remove {self.delta_lb:.1f} lb ({kg:.1f} kg) from {self.station_name}."
            )
        if self.kind == RecommendationKind.ADD_BAGGAGE:
            kg = lb_to_kg(self.delta_lb)
            text = (
                f"Add {self.delta_lb:.1f} lb ({kg:.1f} kg) of permitted, secured load "
                f"to {self.station_name}."
            )
            if self.resulting_station_weight_lb is not None:
                text += f" Target compartment load: {self.resulting_station_weight_lb:.1f} lb."
            return text
        if self.kind == RecommendationKind.MOVE_LOAD:
            kg = lb_to_kg(self.delta_lb)
            return (
                f"Move {self.delta_lb:.1f} lb ({kg:.1f} kg) from {self.station_name} "
                f"to {self.target_station_name}."
            )
        if self.kind == RecommendationKind.SHIFT_FUEL:
            return (
                f"Transfer {self.delta_gal:.1f} US gal of fuel from {self.station_name} "
                f"to {self.target_station_name} (total fuel unchanged)."
            )
        return "Adjustment."


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


def _search_move_load(
    profile: AircraftProfile, calc_input: CalculationInput
) -> list[Recommendation]:
    """Move existing baggage only; never move occupants or an ambiguous CUSTOM load.

    A CUSTOM station may represent equipment, a fixed installation, or another non-movable
    item. Without an explicit "movable cargo" flag, recommending a transfer from it would be an
    unsafe guess. Baggage stations are the only stations whose meaning is unambiguous enough for
    this automatic suggestion.
    """
    movable = [
        station
        for station in profile.stations
        if station.station_type == StationType.BAGGAGE
    ]
    results: list[Recommendation] = []
    for source in movable:
        source_weight = _current_load_weight(calc_input, source.station_id)
        if source_weight <= 0:
            continue
        for destination in movable:
            if destination.station_id == source.station_id:
                continue
            destination_weight = _current_load_weight(calc_input, destination.station_id)
            headroom = source_weight
            if destination.maximum_weight_lb is not None:
                headroom = min(
                    headroom, destination.maximum_weight_lb - destination_weight
                )
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
                        )
                    )
                    break
    return results


def _search_add_baggage(
    profile: AircraftProfile, calc_input: CalculationInput
) -> list[Recommendation]:
    results: list[Recommendation] = []
    for station in profile.baggage_stations:
        # Never recommend adding an unknown amount to a compartment whose published maximum
        # was not entered. The math might work, but the physical compartment limit is unknown.
        if station.maximum_weight_lb is None:
            continue
        current = _current_load_weight(calc_input, station.station_id)
        headroom = station.maximum_weight_lb - current
        if headroom <= 0:
            continue
        steps = min(int(headroom / LOAD_STEP_LB), MAX_STEPS)
        for step in range(1, steps + 1):
            delta = LOAD_STEP_LB * step
            target = current + delta
            candidate = _replace_load(calc_input, station.station_id, target)
            result = _try_calculate(profile, candidate)
            if result and _is_acceptable(result.overall_status):
                results.append(
                    Recommendation(
                        kind=RecommendationKind.ADD_BAGGAGE,
                        station_id=station.station_id,
                        station_name=station.name,
                        delta_lb=delta,
                        resulting_station_weight_lb=target,
                        note=ADDED_LOAD_NOTE,
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
        floor = min_fuel_gal.get(fuel.station_id, Decimal("0"))
        if fuel.starting_gal <= floor:
            continue
        station = profile.station(fuel.station_id)
        steps = min(int((fuel.starting_gal - floor) / FUEL_STEP_GAL), MAX_STEPS)
        for step in range(1, steps + 1):
            delta_gal = FUEL_STEP_GAL * step
            target = fuel.starting_gal - delta_gal
            if target < floor:
                break
            candidate = _replace_fuel(calc_input, fuel.station_id, target)
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
                        note=FUEL_REDUCTION_NOTE,
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
        floor = min_fuel_gal.get(source.station_id, Decimal("0"))
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
                candidate = _replace_fuel(
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
                    )
                )
                break
    return results


_CATEGORY_PRIORITY = {
    RecommendationKind.MOVE_LOAD: 0,
    RecommendationKind.ADD_BAGGAGE: 1,
    RecommendationKind.REDUCE_BAGGAGE: 2,
    RecommendationKind.REDUCE_FUEL: 3,
    RecommendationKind.SHIFT_FUEL: 4,
    RecommendationKind.ADD_FUEL: 5,
}


def generate_recommendations(
    profile: AircraftProfile,
    calc_input: CalculationInput,
    min_fuel_gal: dict[str, Decimal] | None = None,
    max_results: int = 3,
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

    candidates: list[Recommendation] = []
    candidates += _search_move_load(profile, calc_input)
    candidates += _search_add_baggage(profile, calc_input)
    candidates += _search_reduce_baggage(profile, calc_input)
    candidates += _search_reduce_fuel(profile, calc_input, min_fuel_gal)
    if allow_fuel_transfer:
        candidates += _search_shift_fuel(profile, calc_input, min_fuel_gal)
    if allow_add_fuel:
        candidates += _search_add_fuel(profile, calc_input)

    def tiebreak(recommendation: Recommendation) -> Decimal:
        if recommendation.delta_lb is not None:
            return recommendation.delta_lb
        if recommendation.delta_gal is not None:
            return recommendation.delta_gal
        return Decimal("0")

    candidates.sort(
        key=lambda recommendation: (
            _CATEGORY_PRIORITY.get(recommendation.kind, 99),
            tiebreak(recommendation),
        )
    )
    return candidates[:max_results]
