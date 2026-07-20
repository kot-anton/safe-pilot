"""Deterministic recommendation solver.

Every candidate adjustment is applied to a copy of the input and re-run through the full
ramp/takeoff/landing calculator before being offered. Nothing is suggested that the engine
has not itself verified to land inside all configured limits.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.domain.calculator import calculate
from app.domain.envelope import LimitStatus
from app.domain.exceptions import DomainError
from app.domain.models import (
    AircraftProfile,
    CalculationInput,
    FuelStationInput,
    LoadItemInput,
    StationType,
)
from app.domain.units import lb_to_kg

FUEL_STEP_GAL = Decimal("0.1")
LOAD_STEP_LB = Decimal("1")
MAX_STEPS = 2000

class RecommendationKind(str, Enum):
    REDUCE_FUEL = "REDUCE_FUEL"
    ADD_FUEL = "ADD_FUEL"
    REDUCE_BAGGAGE = "REDUCE_BAGGAGE"
    MOVE_LOAD = "MOVE_LOAD"


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

    def describe(self) -> str:
        if self.kind == RecommendationKind.REDUCE_FUEL:
            return (
                f"Reduce fuel in {self.station_name} by {self.delta_gal:.1f} US gal "
                f"({self.delta_lb:.1f} lb)."
            )
        if self.kind == RecommendationKind.ADD_FUEL:
            return (
                f"Add fuel to {self.station_name}: +{self.delta_gal:.1f} US gal "
                f"(+{self.delta_lb:.1f} lb)."
            )
        if self.kind == RecommendationKind.REDUCE_BAGGAGE:
            kg = lb_to_kg(self.delta_lb)
            return f"Reduce load at {self.station_name} by {self.delta_lb:.1f} lb ({kg:.1f} kg)."
        if self.kind == RecommendationKind.MOVE_LOAD:
            kg = lb_to_kg(self.delta_lb)
            return (
                f"Move {self.delta_lb:.1f} lb ({kg:.1f} kg) from {self.station_name} "
                f"to {self.target_station_name}."
            )
        return "Adjustment."


def _is_acceptable(status: LimitStatus) -> bool:
    return status != LimitStatus.OUT_OF_LIMITS


def _try_calculate(profile: AircraftProfile, calc_input: CalculationInput):
    """Recommendation search tries many candidate inputs, some of which are expected to be
    invalid (e.g. a candidate fuel load that would exceed a tank someone else already filled
    differently) -- those are just rejected candidates. Anything else is a real bug and must
    not be swallowed silently."""
    try:
        return calculate(profile, calc_input)
    except DomainError:
        return None


def _replace_fuel(calc_input: CalculationInput, station_id: str, new_starting_gal: Decimal) -> CalculationInput:
    new_fuel = [
        dataclasses.replace(f, starting_gal=new_starting_gal) if f.station_id == station_id else f
        for f in calc_input.fuel
    ]
    return dataclasses.replace(calc_input, fuel=new_fuel)


def _replace_load(calc_input: CalculationInput, station_id: str, new_weight: Decimal) -> CalculationInput:
    new_loads = [
        dataclasses.replace(l, weight_lb=new_weight) if l.station_id == station_id else l
        for l in calc_input.loads
    ]
    return dataclasses.replace(calc_input, loads=new_loads)


def _current_load_weight(calc_input: CalculationInput, station_id: str) -> Decimal:
    for l in calc_input.loads:
        if l.station_id == station_id:
            return l.weight_lb
    return Decimal("0")


def _search_reduce_fuel(
    profile: AircraftProfile,
    calc_input: CalculationInput,
    min_fuel_gal: dict[str, Decimal],
) -> list[Recommendation]:
    results = []
    for fuel in calc_input.fuel:
        floor = min_fuel_gal.get(fuel.station_id, Decimal("0"))
        if fuel.starting_gal <= floor:
            continue
        station = profile.station(fuel.station_id)
        steps = int((fuel.starting_gal - floor) / FUEL_STEP_GAL)
        for step in range(1, min(steps, MAX_STEPS) + 1):
            candidate_gal = fuel.starting_gal - FUEL_STEP_GAL * step
            if candidate_gal < floor:
                break
            candidate_input = _replace_fuel(calc_input, fuel.station_id, candidate_gal)
            result = _try_calculate(profile, candidate_input)
            if result and _is_acceptable(result.overall_status):
                delta_gal = FUEL_STEP_GAL * step
                delta_lb = delta_gal * station.fuel_density_lb_per_gal
                results.append(
                    Recommendation(
                        kind=RecommendationKind.REDUCE_FUEL,
                        station_id=station.station_id,
                        station_name=station.name,
                        delta_lb=delta_lb,
                        delta_gal=delta_gal,
                    )
                )
                break
    return results


def _search_add_fuel(profile: AircraftProfile, calc_input: CalculationInput) -> list[Recommendation]:
    results = []
    for fuel in calc_input.fuel:
        station = profile.station(fuel.station_id)
        headroom_gal = station.maximum_volume_gal - fuel.starting_gal
        if headroom_gal <= 0:
            continue
        steps = int(headroom_gal / FUEL_STEP_GAL)
        for step in range(1, min(steps, MAX_STEPS) + 1):
            candidate_gal = fuel.starting_gal + FUEL_STEP_GAL * step
            candidate_input = _replace_fuel(calc_input, fuel.station_id, candidate_gal)
            result = _try_calculate(profile, candidate_input)
            if result and _is_acceptable(result.overall_status):
                delta_gal = FUEL_STEP_GAL * step
                delta_lb = delta_gal * station.fuel_density_lb_per_gal
                results.append(
                    Recommendation(
                        kind=RecommendationKind.ADD_FUEL,
                        station_id=station.station_id,
                        station_name=station.name,
                        delta_lb=delta_lb,
                        delta_gal=delta_gal,
                    )
                )
                break
    return results


def _search_reduce_baggage(profile: AircraftProfile, calc_input: CalculationInput) -> list[Recommendation]:
    results = []
    for station in profile.baggage_stations:
        current = _current_load_weight(calc_input, station.station_id)
        if current <= 0:
            continue
        steps = int(current / LOAD_STEP_LB)
        for step in range(1, min(steps, MAX_STEPS) + 1):
            candidate_weight = current - LOAD_STEP_LB * step
            if candidate_weight < 0:
                break
            candidate_input = _replace_load(calc_input, station.station_id, candidate_weight)
            result = _try_calculate(profile, candidate_input)
            if result and _is_acceptable(result.overall_status):
                delta = LOAD_STEP_LB * step
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


PASSENGER_MOVE_NOTE = (
    "Use actual occupant weights and permitted seating positions -- this does not mean part "
    "of one person can be moved. It reflects the minimum total reseating needed."
)


def _search_move_passengers(profile: AircraftProfile, calc_input: CalculationInput) -> list[Recommendation]:
    """Front/rear seat inputs are aggregated occupant totals, not individual people -- so a
    'move weight' recommendation here means reseating occupants between rows (e.g. moving a
    passenger to the back seat), not fractionally splitting a person."""
    seat_types = {StationType.FRONT_SEATS, StationType.REAR_SEATS}
    seat_stations = [s for s in profile.stations if s.station_type in seat_types]
    results = []
    for source in seat_stations:
        source_weight = _current_load_weight(calc_input, source.station_id)
        if source_weight <= 0:
            continue
        for dest in seat_stations:
            if dest.station_id == source.station_id:
                continue
            dest_weight = _current_load_weight(calc_input, dest.station_id)
            headroom = source_weight
            if dest.maximum_weight_lb is not None:
                headroom = min(headroom, dest.maximum_weight_lb - dest_weight)
            if headroom <= 0:
                continue
            steps = int(headroom / LOAD_STEP_LB)
            for step in range(1, min(steps, MAX_STEPS) + 1):
                delta = LOAD_STEP_LB * step
                candidate_input = _replace_load(calc_input, source.station_id, source_weight - delta)
                candidate_input = _replace_load(candidate_input, dest.station_id, dest_weight + delta)
                result = _try_calculate(profile, candidate_input)
                if result and _is_acceptable(result.overall_status):
                    results.append(
                        Recommendation(
                            kind=RecommendationKind.MOVE_LOAD,
                            station_id=source.station_id,
                            station_name=source.name,
                            target_station_id=dest.station_id,
                            target_station_name=dest.name,
                            delta_lb=delta,
                            note=PASSENGER_MOVE_NOTE,
                        )
                    )
                    break
    return results


def _search_move_load(profile: AircraftProfile, calc_input: CalculationInput) -> list[Recommendation]:
    """Only allowed between non-passenger stations (baggage/custom) — individual bags
    can be fully reassigned since they're not people."""
    movable_types = {StationType.BAGGAGE, StationType.CUSTOM}
    movable_stations = [s for s in profile.stations if s.station_type in movable_types]
    results = []
    for source in movable_stations:
        source_weight = _current_load_weight(calc_input, source.station_id)
        if source_weight <= 0:
            continue
        for dest in movable_stations:
            if dest.station_id == source.station_id:
                continue
            dest_weight = _current_load_weight(calc_input, dest.station_id)
            headroom = source_weight
            if dest.maximum_weight_lb is not None:
                headroom = min(headroom, dest.maximum_weight_lb - dest_weight)
            if headroom <= 0:
                continue
            steps = int(headroom / LOAD_STEP_LB)
            for step in range(1, min(steps, MAX_STEPS) + 1):
                delta = LOAD_STEP_LB * step
                candidate_input = _replace_load(calc_input, source.station_id, source_weight - delta)
                candidate_input = _replace_load(candidate_input, dest.station_id, dest_weight + delta)
                result = _try_calculate(profile, candidate_input)
                if result and _is_acceptable(result.overall_status):
                    results.append(
                        Recommendation(
                            kind=RecommendationKind.MOVE_LOAD,
                            station_id=source.station_id,
                            station_name=source.name,
                            target_station_id=dest.station_id,
                            target_station_name=dest.name,
                            delta_lb=delta,
                        )
                    )
                    break
    return results


_CATEGORY_PRIORITY = {
    RecommendationKind.MOVE_LOAD: 0,
    RecommendationKind.REDUCE_BAGGAGE: 1,
    RecommendationKind.REDUCE_FUEL: 2,
    RecommendationKind.ADD_FUEL: 3,
}


def generate_recommendations(
    profile: AircraftProfile,
    calc_input: CalculationInput,
    min_fuel_gal: dict[str, Decimal] | None = None,
    max_results: int = 3,
) -> list[Recommendation]:
    """Returns up to `max_results` verified, mathematically valid load adjustments.

    Search proceeds in the required preference order (move passengers/load, reduce baggage,
    reduce fuel, add fuel). That category order is the primary sort key --
    smallest-change-first is only the tiebreaker *within* a category, so e.g. a 2 lb fuel
    reduction never displaces a 1 lb load move from its preferred position.
    """
    min_fuel_gal = min_fuel_gal or {}

    ordered_candidates: list[Recommendation] = []
    ordered_candidates += _search_move_passengers(profile, calc_input)
    ordered_candidates += _search_move_load(profile, calc_input)
    ordered_candidates += _search_reduce_baggage(profile, calc_input)
    ordered_candidates += _search_reduce_fuel(profile, calc_input, min_fuel_gal)
    ordered_candidates += _search_add_fuel(profile, calc_input)

    ordered_candidates.sort(
        key=lambda r: (
            _CATEGORY_PRIORITY.get(r.kind, 99),
            r.delta_lb if r.delta_lb is not None else Decimal("0"),
        )
    )
    return ordered_candidates[:max_results]
