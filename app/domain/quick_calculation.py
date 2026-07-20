"""The reduced 4-question calculation: front seats, rear seats, baggage, total fuel.

Reuses the same envelope/status conventions as the full ramp/takeoff/landing calculator
(see app.domain.calculator), but fuel is entered as one total-gallons number and may only be
resolvable to a CG *range* rather than one exact value when tanks have different ARMs and the
actual split is unknown -- see app.domain.fuel_allocation for why, and never invent one
number when a range is all that's mathematically justified.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.envelope import CGCheckResult, LimitStatus
from app.domain.exceptions import InvalidInputError
from app.domain.fuel_allocation import (
    FuelAllocationResult,
    FuelRangeStatus,
    FuelTankSpec,
    classify_cg_range,
    compute_fuel_allocation,
)
from app.domain.models import AircraftProfile, StationType

_WORST_ORDER = {LimitStatus.WITHIN: 0, LimitStatus.ON_LIMIT: 1, LimitStatus.OUT_OF_LIMITS: 2}


def _worse(a: LimitStatus, b: LimitStatus) -> LimitStatus:
    return a if _WORST_ORDER[a] >= _WORST_ORDER[b] else b


@dataclass(frozen=True)
class QuickCalculationResult:
    total_weight_lb: Decimal
    weight_limit_lb: Decimal | None
    weight_status: LimitStatus
    fuel_allocation: FuelAllocationResult
    cg_forward: Decimal
    cg_aft: Decimal
    fuel_range_status: FuelRangeStatus | None
    forward_check: CGCheckResult | None
    aft_check: CGCheckResult | None
    overall_status: LimitStatus
    is_exact: bool

    @property
    def weight_margin_lb(self) -> Decimal | None:
        if self.weight_limit_lb is None:
            return None
        return self.weight_limit_lb - self.total_weight_lb


def _station_for_type(profile: AircraftProfile, station_type: StationType):
    for s in profile.stations:
        if s.station_type == station_type:
            return s
    return None


def _apply_seat_or_baggage_load(
    profile: AircraftProfile,
    station_type: StationType,
    weight_lb: Decimal,
    label: str,
    total_weight: Decimal,
    total_moment: Decimal,
) -> tuple[Decimal, Decimal]:
    if weight_lb < 0:
        raise InvalidInputError(f"{label} weight cannot be negative")
    station = _station_for_type(profile, station_type)
    if station is None:
        if weight_lb > 0:
            raise InvalidInputError(f"This aircraft has no {label.lower()} station configured")
        return total_weight, total_moment
    if station.maximum_weight_lb is not None and weight_lb > station.maximum_weight_lb:
        raise InvalidInputError(
            f"{label} load ({weight_lb} lb) exceeds the station maximum ({station.maximum_weight_lb} lb)"
        )
    return total_weight + weight_lb, total_moment + weight_lb * station.default_arm_in


def run_quick_calculation(
    profile: AircraftProfile,
    front_lb: Decimal,
    rear_lb: Decimal,
    baggage_lb: Decimal,
    total_fuel_gal: Decimal,
) -> QuickCalculationResult:
    total_weight = profile.basic_empty_weight_lb
    total_moment = profile.basic_empty_moment_lb_in

    total_weight, total_moment = _apply_seat_or_baggage_load(
        profile, StationType.FRONT_SEATS, front_lb, "Front seats", total_weight, total_moment
    )
    total_weight, total_moment = _apply_seat_or_baggage_load(
        profile, StationType.REAR_SEATS, rear_lb, "Rear seats", total_weight, total_moment
    )
    total_weight, total_moment = _apply_seat_or_baggage_load(
        profile, StationType.BAGGAGE, baggage_lb, "Baggage", total_weight, total_moment
    )

    tanks = [
        FuelTankSpec(
            station_id=s.station_id,
            name=s.name,
            usable_capacity_gal=s.maximum_volume_gal,
            arm_in=s.default_arm_in,
            density_lb_per_gal=s.fuel_density_lb_per_gal,
        )
        for s in profile.fuel_stations
    ]
    allocation = compute_fuel_allocation(tanks, total_fuel_gal)

    total_weight += allocation.total_weight_lb
    min_moment_total = total_moment + allocation.min_moment_lb_in
    max_moment_total = total_moment + allocation.max_moment_lb_in

    cg_from_min = min_moment_total / total_weight
    cg_from_max = max_moment_total / total_weight
    cg_forward, cg_aft = (
        (cg_from_min, cg_from_max) if cg_from_min <= cg_from_max else (cg_from_max, cg_from_min)
    )

    weight_limit = profile.max_takeoff_weight_lb
    if total_weight > weight_limit:
        weight_status = LimitStatus.OUT_OF_LIMITS
    elif total_weight == weight_limit:
        weight_status = LimitStatus.ON_LIMIT
    else:
        weight_status = LimitStatus.WITHIN

    fuel_range_status, forward_check, aft_check = classify_cg_range(
        profile.envelope, total_weight, cg_forward, cg_aft
    )

    if fuel_range_status is None:
        cg_overall = LimitStatus.WITHIN
    elif fuel_range_status == FuelRangeStatus.WITHIN_ALL:
        cg_overall = LimitStatus.WITHIN
        if forward_check.status == LimitStatus.ON_LIMIT or aft_check.status == LimitStatus.ON_LIMIT:
            cg_overall = LimitStatus.ON_LIMIT
    else:
        # OUT_ALL or EXACT_SPLIT_REQUIRED -- neither justifies claiming WITHIN LIMITS.
        cg_overall = LimitStatus.OUT_OF_LIMITS

    overall = _worse(weight_status, cg_overall)

    return QuickCalculationResult(
        total_weight_lb=total_weight,
        weight_limit_lb=weight_limit,
        weight_status=weight_status,
        fuel_allocation=allocation,
        cg_forward=cg_forward,
        cg_aft=cg_aft,
        fuel_range_status=fuel_range_status,
        forward_check=forward_check,
        aft_check=aft_check,
        overall_status=overall,
        is_exact=allocation.is_exact,
    )
