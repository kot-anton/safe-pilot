"""Recommendations for the standard four-input calculation.

Unlike the Advanced solver, this module keeps fuel as one total-gallons quantity. Every proposed
change is re-run through ``run_quick_calculation`` and is accepted only when it works for every
physically possible fuel split represented by the profile. Front<->Rear seat-shift suggestions
are phrased as a plain weight shift ("Move X lb from Front Seats to Rear Seats") without
asserting who moves -- the app has no way to know who is sitting where.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.domain.envelope import LimitStatus
from app.domain.exceptions import DomainError
from app.domain.fuel_allocation import FuelRangeStatus
from app.domain.models import AircraftProfile, StationType
from app.domain.quick_calculation import (
    QuickCalculationResult,
    quick_station_for_type,
    run_quick_calculation,
)
from app.domain.units import compact_decimal, lb_to_kg

LOAD_STEP_LB = Decimal("1")
FUEL_STEP_GAL = Decimal("0.1")
MAX_LOAD_STEPS = 5000
MAX_FUEL_STEPS = 5000


class QuickRecommendationKind(str, Enum):
    MOVE_LOAD = "MOVE_LOAD"
    REDUCE_BAGGAGE = "REDUCE_BAGGAGE"
    ADD_BAGGAGE = "ADD_BAGGAGE"
    REDUCE_FUEL = "REDUCE_FUEL"


@dataclass(frozen=True)
class QuickRecommendation:
    kind: QuickRecommendationKind
    delta_lb: Decimal | None = None
    delta_gal: Decimal | None = None
    station_name: str | None = None
    target_station_name: str | None = None
    target_baggage_lb: Decimal | None = None
    target_total_fuel_gal: Decimal | None = None

    def describe(self) -> str:
        def display(value: Decimal) -> str:
            return compact_decimal(value, decimal_places=1)

        if self.kind == QuickRecommendationKind.MOVE_LOAD:
            kg = lb_to_kg(self.delta_lb)
            return (
                f"Move {display(self.delta_lb)} lb ({display(kg)} kg) from "
                f"{self.station_name} to {self.target_station_name}."
            )
        if self.kind == QuickRecommendationKind.REDUCE_BAGGAGE:
            kg = lb_to_kg(self.delta_lb)
            text = (
                f"Remove {display(self.delta_lb)} lb ({display(kg)} kg) from "
                f"{self.station_name}."
            )
            if self.target_baggage_lb is not None:
                text += f" Target baggage load: {display(self.target_baggage_lb)} lb."
            return text
        if self.kind == QuickRecommendationKind.ADD_BAGGAGE:
            kg = lb_to_kg(self.delta_lb)
            return f"Add {display(self.delta_lb)} lb ({display(kg)} kg) to {self.station_name}."
        if self.kind == QuickRecommendationKind.REDUCE_FUEL:
            text = f"Reduce total usable fuel by {display(self.delta_gal)} US gal."
            if self.delta_lb is not None:
                text += f" Approximate weight reduction: {display(self.delta_lb)} lb."
            if self.target_total_fuel_gal is not None:
                text += (
                    " Target total usable fuel: "
                    f"{display(self.target_total_fuel_gal)} gal."
                )
            return text
        return "Adjustment."


def _candidate_is_acceptable(result: QuickCalculationResult) -> bool:
    if result.overall_status == LimitStatus.OUT_OF_LIMITS:
        return False
    if result.fuel_range_status is None:
        # CG was not evaluated, but a weight-only violation can still be corrected truthfully.
        return True
    return result.fuel_range_status == FuelRangeStatus.WITHIN_ALL


def _try_quick(
    profile: AircraftProfile,
    front_lb: Decimal,
    rear_lb: Decimal,
    baggage_lb: Decimal,
    total_fuel_gal: Decimal,
) -> QuickCalculationResult | None:
    try:
        return run_quick_calculation(
            profile,
            front_lb=front_lb,
            rear_lb=rear_lb,
            baggage_lb=baggage_lb,
            total_fuel_gal=total_fuel_gal,
        )
    except DomainError:
        return None


def _common_fuel_density(profile: AircraftProfile) -> Decimal | None:
    densities = {station.fuel_density_lb_per_gal for station in profile.fuel_stations}
    if len(densities) != 1:
        return None
    return next(iter(densities))


def _search_move_seats(
    profile: AircraftProfile,
    front_lb: Decimal,
    rear_lb: Decimal,
    baggage_lb: Decimal,
    total_fuel_gal: Decimal,
) -> list[QuickRecommendation]:
    """Suggest shifting weight between the combined Front and Rear seat totals.

    Phrased as a plain weight shift ("Move X lb from Front Seats to Rear Seats") -- the app has
    no way to know who is sitting where, so it never asserts who should move.
    """
    front_station = quick_station_for_type(profile, StationType.FRONT_SEATS, "Front seats")
    rear_station = quick_station_for_type(profile, StationType.REAR_SEATS, "Rear seats")
    if front_station is None or rear_station is None:
        return []

    results: list[QuickRecommendation] = []
    for source_lb, source_station, dest_station in (
        (front_lb, front_station, rear_station),
        (rear_lb, rear_station, front_station),
    ):
        if source_lb <= 0:
            continue
        steps = min(int(source_lb / LOAD_STEP_LB), MAX_LOAD_STEPS)
        for step in range(1, steps + 1):
            delta = LOAD_STEP_LB * step
            if source_station.station_id == front_station.station_id:
                new_front, new_rear = front_lb - delta, rear_lb + delta
            else:
                new_front, new_rear = front_lb + delta, rear_lb - delta
            result = _try_quick(profile, new_front, new_rear, baggage_lb, total_fuel_gal)
            if result and _candidate_is_acceptable(result):
                results.append(
                    QuickRecommendation(
                        kind=QuickRecommendationKind.MOVE_LOAD,
                        delta_lb=delta,
                        station_name=source_station.name,
                        target_station_name=dest_station.name,
                    )
                )
                break
    return results


def generate_quick_recommendations(
    profile: AircraftProfile,
    *,
    front_lb: Decimal,
    rear_lb: Decimal,
    baggage_lb: Decimal,
    total_fuel_gal: Decimal,
    max_results: int = 3,
) -> list[QuickRecommendation]:
    """Return only adjustments verified for every possible total-fuel distribution."""
    candidates: list[QuickRecommendation] = []
    baggage_station = quick_station_for_type(profile, StationType.BAGGAGE, "Baggage")

    candidates += _search_move_seats(profile, front_lb, rear_lb, baggage_lb, total_fuel_gal)

    if baggage_station is not None and baggage_lb > 0:
        for step in range(1, min(int(baggage_lb / LOAD_STEP_LB), MAX_LOAD_STEPS) + 1):
            delta = LOAD_STEP_LB * step
            target = baggage_lb - delta
            result = _try_quick(profile, front_lb, rear_lb, target, total_fuel_gal)
            if result and _candidate_is_acceptable(result):
                candidates.append(
                    QuickRecommendation(
                        kind=QuickRecommendationKind.REDUCE_BAGGAGE,
                        delta_lb=delta,
                        station_name=baggage_station.name,
                        target_baggage_lb=target,
                    )
                )
                break

    if baggage_station is not None:
        baseline = _try_quick(profile, front_lb, rear_lb, baggage_lb, total_fuel_gal)
        headroom = baseline.weight_margin_lb if baseline is not None else None
        if headroom is not None and headroom > 0:
            steps = min(int(headroom / LOAD_STEP_LB), MAX_LOAD_STEPS)
            for step in range(1, steps + 1):
                delta = LOAD_STEP_LB * step
                target = baggage_lb + delta
                result = _try_quick(profile, front_lb, rear_lb, target, total_fuel_gal)
                if result and _candidate_is_acceptable(result):
                    candidates.append(
                        QuickRecommendation(
                            kind=QuickRecommendationKind.ADD_BAGGAGE,
                            delta_lb=delta,
                            station_name=baggage_station.name,
                            target_baggage_lb=target,
                        )
                    )
                    break

    density = _common_fuel_density(profile)
    if total_fuel_gal > 0 and density is not None:
        steps = min(int(total_fuel_gal / FUEL_STEP_GAL), MAX_FUEL_STEPS)
        for step in range(1, steps + 1):
            delta = FUEL_STEP_GAL * step
            target = total_fuel_gal - delta
            result = _try_quick(profile, front_lb, rear_lb, baggage_lb, target)
            if result and _candidate_is_acceptable(result):
                candidates.append(
                    QuickRecommendation(
                        kind=QuickRecommendationKind.REDUCE_FUEL,
                        delta_gal=delta,
                        delta_lb=delta * density,
                        target_total_fuel_gal=target,
                    )
                )
                break

    priority = {
        QuickRecommendationKind.MOVE_LOAD: 0,
        QuickRecommendationKind.REDUCE_BAGGAGE: 1,
        QuickRecommendationKind.REDUCE_FUEL: 2,
        QuickRecommendationKind.ADD_BAGGAGE: 3,
    }

    def amount(recommendation: QuickRecommendation) -> Decimal:
        if recommendation.delta_lb is not None:
            return recommendation.delta_lb
        if recommendation.delta_gal is not None:
            return recommendation.delta_gal
        return Decimal("0")

    candidates.sort(key=lambda rec: (priority[rec.kind], amount(rec)))
    return candidates[:max_results]
