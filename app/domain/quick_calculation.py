"""Standard four-input Weight & Balance calculation.

The inputs are combined front-seat weight, combined rear-seat weight, combined baggage weight,
and total usable fuel. When the actual split among tanks with different ARMs is unknown, the
result is an honest CG range rather than a fabricated exact CG.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.envelope import CGCheckResult, LimitStatus
from app.domain.exceptions import InvalidInputError
from app.domain.fuel_allocation import (
    FuelAllocation,
    FuelAllocationResult,
    FuelInputMode,
    FuelRangeStatus,
    FuelTankSpec,
    classify_cg_range,
    compute_fuel_allocation,
)
from app.domain.models import AircraftProfile, StationProfile, StationType

_WORST_ORDER = {
    LimitStatus.WITHIN: 0,
    LimitStatus.ON_LIMIT: 1,
    LimitStatus.OUT_OF_LIMITS: 2,
}


_QUICK_SUPPORTED_STATION_TYPES = {
    StationType.FRONT_SEATS,
    StationType.REAR_SEATS,
    StationType.BAGGAGE,
    StationType.FUEL,
}


def _worse(a: LimitStatus, b: LimitStatus) -> LimitStatus:
    return a if _WORST_ORDER[a] >= _WORST_ORDER[b] else b


@dataclass(frozen=True)
class QuickStationLimitViolation:
    station_id: str
    station_name: str
    actual_weight_lb: Decimal
    maximum_weight_lb: Decimal


@dataclass(frozen=True)
class QuickCalculationResult:
    total_weight_lb: Decimal
    weight_limit_lb: Decimal | None
    takeoff_weight_status: LimitStatus
    zero_fuel_weight_lb: Decimal
    zero_fuel_limit_lb: Decimal | None
    zero_fuel_status: LimitStatus
    station_status: LimitStatus
    station_violations: tuple[QuickStationLimitViolation, ...]
    # Aggregate of takeoff weight, zero-fuel weight, and individual station weight limits.
    # Kept for compatibility with existing callers that need one load-related status.
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

    @property
    def zero_fuel_margin_lb(self) -> Decimal | None:
        if self.zero_fuel_limit_lb is None:
            return None
        return self.zero_fuel_limit_lb - self.zero_fuel_weight_lb


def quick_station_for_type(
    profile: AircraftProfile, station_type: StationType, label: str
) -> StationProfile | None:
    """Return the one station representable by a combined quick-flow input.

    Multiple baggage compartments or multiple passenger rows with different ARMs cannot be
    collapsed into one number without losing moment information. Such profiles must use the
    Advanced per-station flow.
    """
    matches = [station for station in profile.stations if station.station_type == station_type]
    if len(matches) > 1:
        raise InvalidInputError(
            f"Standard calculation cannot combine multiple {label.lower()} stations. "
            "Use Advanced / Landing and enter each station separately."
        )
    station = matches[0] if matches else None
    if station is not None and station.is_adjustable_arm:
        raise InvalidInputError(
            f"{station.name} has an adjustable ARM. Use Advanced / Landing and enter the actual ARM."
        )
    return station


def validate_quick_profile(profile: AircraftProfile) -> None:
    """Fail before asking four quick-flow questions when the profile cannot be represented.

    A CUSTOM or legacy PASSENGER station is a per-flight load whose moment would otherwise be
    silently omitted by the combined front/rear/baggage UI. That is never an acceptable
    simplification: such aircraft must use the Advanced per-station calculation. The same early
    validation also catches duplicate/adjustable combined stations and mixed fuel densities.
    """
    unsupported = [
        station
        for station in profile.stations
        if station.station_type not in _QUICK_SUPPORTED_STATION_TYPES
    ]
    if unsupported:
        names = ", ".join(station.name for station in unsupported)
        raise InvalidInputError(
            "Standard calculation cannot represent these per-flight stations: "
            f"{names}. Use Advanced / Landing and enter each station separately."
        )

    # Validate the one-station-per-combined-field contract now, not after the user has answered
    # the entire wizard.
    quick_station_for_type(profile, StationType.FRONT_SEATS, "Front seats")
    quick_station_for_type(profile, StationType.REAR_SEATS, "Rear seats")
    quick_station_for_type(profile, StationType.BAGGAGE, "Baggage")

    tanks = [
        FuelTankSpec(
            station_id=station.station_id,
            name=station.name,
            usable_capacity_gal=station.maximum_volume_gal,
            arm_in=station.default_arm_in,
            density_lb_per_gal=station.fuel_density_lb_per_gal,
        )
        for station in profile.fuel_stations
    ]
    if tanks:
        # Zero gallons is enough to validate duplicate IDs, capacities and one common density.
        compute_fuel_allocation(tanks, Decimal("0"))


def _validate_non_negative_finite(value: Decimal, label: str) -> None:
    if not value.is_finite():
        raise InvalidInputError(f"{label} must be finite")
    if value < 0:
        raise InvalidInputError(f"{label} cannot be negative")


def _apply_seat_or_baggage_load(
    profile: AircraftProfile,
    station_type: StationType,
    weight_lb: Decimal,
    label: str,
    total_weight: Decimal,
    total_moment: Decimal,
) -> tuple[Decimal, Decimal, QuickStationLimitViolation | None]:
    """Apply a normal load and report a published station-limit exceedance as a result.

    Exceeding a station limit is an out-of-limits loading condition, not malformed input. The
    quick flow must therefore finish the calculation and, for baggage, be able to recommend the
    amount to remove instead of failing with a generic validation error.
    """
    _validate_non_negative_finite(weight_lb, f"{label} weight")
    station = quick_station_for_type(profile, station_type, label)
    if station is None:
        if weight_lb > 0:
            raise InvalidInputError(f"This aircraft has no {label.lower()} station configured")
        return total_weight, total_moment, None

    violation = None
    if station.maximum_weight_lb is not None and weight_lb > station.maximum_weight_lb:
        violation = QuickStationLimitViolation(
            station_id=station.station_id,
            station_name=station.name,
            actual_weight_lb=weight_lb,
            maximum_weight_lb=station.maximum_weight_lb,
        )

    return (
        total_weight + weight_lb,
        total_moment + weight_lb * station.default_arm_in,
        violation,
    )


def _empty_fuel_allocation() -> FuelAllocationResult:
    empty = FuelAllocation(gallons_by_station={}, total_moment_lb_in=Decimal("0"))
    return FuelAllocationResult(
        mode=FuelInputMode.SINGLE_ARM,
        total_gal=Decimal("0"),
        total_weight_lb=Decimal("0"),
        min_allocation=empty,
        max_allocation=empty,
    )


def _limit_status(value: Decimal, limit: Decimal | None) -> LimitStatus:
    if limit is None:
        return LimitStatus.WITHIN
    if value > limit:
        return LimitStatus.OUT_OF_LIMITS
    if value == limit:
        return LimitStatus.ON_LIMIT
    return LimitStatus.WITHIN


def run_quick_calculation(
    profile: AircraftProfile,
    front_lb: Decimal,
    rear_lb: Decimal,
    baggage_lb: Decimal,
    total_fuel_gal: Decimal,
) -> QuickCalculationResult:
    validate_quick_profile(profile)
    total_weight = profile.basic_empty_weight_lb
    total_moment = profile.basic_empty_moment_lb_in
    station_violations: list[QuickStationLimitViolation] = []

    for station_type, weight, label in (
        (StationType.FRONT_SEATS, front_lb, "Front seats"),
        (StationType.REAR_SEATS, rear_lb, "Rear seats"),
        (StationType.BAGGAGE, baggage_lb, "Baggage"),
    ):
        total_weight, total_moment, violation = _apply_seat_or_baggage_load(
            profile,
            station_type,
            weight,
            label,
            total_weight,
            total_moment,
        )
        if violation is not None:
            station_violations.append(violation)

    # Zero-fuel weight is evaluated before usable fuel is added.
    zero_fuel_weight = total_weight
    zero_fuel_status = _limit_status(zero_fuel_weight, profile.max_zero_fuel_weight_lb)
    station_status = (
        LimitStatus.OUT_OF_LIMITS if station_violations else LimitStatus.WITHIN
    )

    _validate_non_negative_finite(total_fuel_gal, "Total fuel")
    tanks = [
        FuelTankSpec(
            station_id=station.station_id,
            name=station.name,
            usable_capacity_gal=station.maximum_volume_gal,
            arm_in=station.default_arm_in,
            density_lb_per_gal=station.fuel_density_lb_per_gal,
        )
        for station in profile.fuel_stations
    ]
    if tanks:
        allocation = compute_fuel_allocation(tanks, total_fuel_gal)
    elif total_fuel_gal == 0:
        allocation = _empty_fuel_allocation()
    else:
        raise InvalidInputError("This aircraft has no fuel-tank stations configured")

    total_weight += allocation.total_weight_lb
    if total_weight <= 0:
        raise InvalidInputError("Calculated aircraft weight must be greater than zero")

    min_moment_total = total_moment + allocation.min_moment_lb_in
    max_moment_total = total_moment + allocation.max_moment_lb_in
    cg_from_min = min_moment_total / total_weight
    cg_from_max = max_moment_total / total_weight
    cg_forward, cg_aft = (
        (cg_from_min, cg_from_max)
        if cg_from_min <= cg_from_max
        else (cg_from_max, cg_from_min)
    )

    takeoff_weight_status = _limit_status(total_weight, profile.max_takeoff_weight_lb)
    weight_status = _worse(takeoff_weight_status, zero_fuel_status)
    weight_status = _worse(weight_status, station_status)

    fuel_range_status, forward_check, aft_check = classify_cg_range(
        profile.envelope, total_weight, cg_forward, cg_aft
    )

    if fuel_range_status is None:
        cg_overall = LimitStatus.WITHIN
    elif fuel_range_status == FuelRangeStatus.WITHIN_ALL:
        cg_overall = LimitStatus.WITHIN
        if (
            forward_check.status == LimitStatus.ON_LIMIT
            or aft_check.status == LimitStatus.ON_LIMIT
        ):
            cg_overall = LimitStatus.ON_LIMIT
    else:
        # OUT_ALL and EXACT_SPLIT_REQUIRED both prohibit a claim of "within limits".
        cg_overall = LimitStatus.OUT_OF_LIMITS

    return QuickCalculationResult(
        total_weight_lb=total_weight,
        weight_limit_lb=profile.max_takeoff_weight_lb,
        takeoff_weight_status=takeoff_weight_status,
        zero_fuel_weight_lb=zero_fuel_weight,
        zero_fuel_limit_lb=profile.max_zero_fuel_weight_lb,
        zero_fuel_status=zero_fuel_status,
        station_status=station_status,
        station_violations=tuple(station_violations),
        weight_status=weight_status,
        fuel_allocation=allocation,
        cg_forward=cg_forward,
        cg_aft=cg_aft,
        fuel_range_status=fuel_range_status,
        forward_check=forward_check,
        aft_check=aft_check,
        overall_status=_worse(weight_status, cg_overall),
        is_exact=allocation.is_exact,
    )
