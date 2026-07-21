"""Recommendations for the standard four-input calculation.

Unlike the Advanced solver, this module keeps fuel as one total-gallons quantity. Every proposed
change is re-run through ``run_quick_calculation`` and is accepted only when it works for every
physically possible fuel split represented by the profile. It never suggests reseating people.
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
from app.domain.recommendations import ADDED_LOAD_NOTE, FUEL_REDUCTION_NOTE
from app.domain.units import lb_to_kg

LOAD_STEP_LB = Decimal("1")
FUEL_STEP_GAL = Decimal("0.1")
MAX_LOAD_STEPS = 5000
MAX_FUEL_STEPS = 5000


class QuickRecommendationKind(str, Enum):
    ADD_BAGGAGE = "ADD_BAGGAGE"
    REDUCE_BAGGAGE = "REDUCE_BAGGAGE"
    REDUCE_FUEL = "REDUCE_FUEL"


@dataclass(frozen=True)
class QuickRecommendation:
    kind: QuickRecommendationKind
    delta_lb: Decimal | None = None
    delta_gal: Decimal | None = None
    station_name: str | None = None
    target_baggage_lb: Decimal | None = None
    target_total_fuel_gal: Decimal | None = None
    note: str | None = None

    def describe(self) -> str:
        if self.kind == QuickRecommendationKind.ADD_BAGGAGE:
            kg = lb_to_kg(self.delta_lb)
            text = (
                f"Add {self.delta_lb:.1f} lb ({kg:.1f} kg) of permitted, secured load "
                f"to {self.station_name}."
            )
            if self.target_baggage_lb is not None:
                text += f" Target baggage load: {self.target_baggage_lb:.1f} lb."
            return text
        if self.kind == QuickRecommendationKind.REDUCE_BAGGAGE:
            kg = lb_to_kg(self.delta_lb)
            text = f"Remove {self.delta_lb:.1f} lb ({kg:.1f} kg) from {self.station_name}."
            if self.target_baggage_lb is not None:
                text += f" Target baggage load: {self.target_baggage_lb:.1f} lb."
            return text
        if self.kind == QuickRecommendationKind.REDUCE_FUEL:
            text = f"Reduce total usable fuel by {self.delta_gal:.1f} US gal."
            if self.delta_lb is not None:
                text += f" Approximate weight reduction: {self.delta_lb:.1f} lb."
            if self.target_total_fuel_gal is not None:
                text += f" Target total usable fuel: {self.target_total_fuel_gal:.1f} gal."
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

    # Adding weight is useful primarily for a forward-CG condition. It is disabled when the
    # compartment limit is unknown, because the solver cannot prove the proposed load is allowed.
    if (
        profile.envelope is not None
        and baggage_station is not None
        and baggage_station.maximum_weight_lb is not None
        and baggage_lb < baggage_station.maximum_weight_lb
    ):
        headroom = baggage_station.maximum_weight_lb - baggage_lb
        for step in range(1, min(int(headroom / LOAD_STEP_LB), MAX_LOAD_STEPS) + 1):
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
                        note=ADDED_LOAD_NOTE,
                    )
                )
                break

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
                        note=FUEL_REDUCTION_NOTE,
                    )
                )
                break

    priority = {
        QuickRecommendationKind.ADD_BAGGAGE: 0,
        QuickRecommendationKind.REDUCE_BAGGAGE: 1,
        QuickRecommendationKind.REDUCE_FUEL: 2,
    }

    def amount(recommendation: QuickRecommendation) -> Decimal:
        if recommendation.delta_lb is not None:
            return recommendation.delta_lb
        if recommendation.delta_gal is not None:
            return recommendation.delta_gal
        return Decimal("0")

    candidates.sort(key=lambda rec: (priority[rec.kind], amount(rec)))
    return candidates[:max_results]
