"""Allocation math for the standard one-number usable-fuel workflow.

When a pilot knows total usable fuel but not the distribution among tanks with different ARMs,
the physically possible minimum and maximum fuel moments are calculated. The application never
invents a precise split. A fixed allocation is used only when the aircraft profile explicitly
contains such a confirmed rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.domain.envelope import CGCheckResult, CGEnvelope, EPSILON
from app.domain.exceptions import InvalidInputError
from app.domain.units import compact_decimal


class FuelInputMode(str, Enum):
    SINGLE_ARM = "SINGLE_ARM"
    UNKNOWN_SPLIT_RANGE = "UNKNOWN_SPLIT_RANGE"
    FIXED_ALLOCATION = "FIXED_ALLOCATION"


class FuelRangeStatus(str, Enum):
    WITHIN_ALL = "WITHIN_ALL"
    OUT_ALL = "OUT_ALL"
    EXACT_SPLIT_REQUIRED = "EXACT_SPLIT_REQUIRED"


@dataclass(frozen=True)
class FuelTankSpec:
    station_id: str
    name: str
    usable_capacity_gal: Decimal
    arm_in: Decimal
    density_lb_per_gal: Decimal
    allocation_order: int | None = None
    fixed_full_quantity_gal: Decimal | None = None


@dataclass(frozen=True)
class FuelAllocation:
    """One concrete, capacity-respecting split of total fuel across tanks."""

    gallons_by_station: dict[str, Decimal]
    total_moment_lb_in: Decimal


@dataclass(frozen=True)
class FuelAllocationResult:
    mode: FuelInputMode
    total_gal: Decimal
    total_weight_lb: Decimal
    min_allocation: FuelAllocation
    max_allocation: FuelAllocation

    @property
    def is_exact(self) -> bool:
        return self.min_allocation.total_moment_lb_in == self.max_allocation.total_moment_lb_in

    @property
    def min_moment_lb_in(self) -> Decimal:
        return self.min_allocation.total_moment_lb_in

    @property
    def max_moment_lb_in(self) -> Decimal:
        return self.max_allocation.total_moment_lb_in


def total_capacity_gal(tanks: list[FuelTankSpec]) -> Decimal:
    return sum((tank.usable_capacity_gal for tank in tanks), Decimal("0"))


def detect_mode(tanks: list[FuelTankSpec]) -> FuelInputMode:
    """Detect the safe mode from tank ARMs; never infer a fill/transfer order."""
    if len(tanks) <= 1:
        return FuelInputMode.SINGLE_ARM
    arms = {tank.arm_in for tank in tanks}
    return FuelInputMode.SINGLE_ARM if len(arms) == 1 else FuelInputMode.UNKNOWN_SPLIT_RANGE


def _validate_group(tanks: list[FuelTankSpec], total_gal: Decimal) -> Decimal:
    if not tanks:
        raise InvalidInputError("Fuel system has no fuel-tank stations")
    if not total_gal.is_finite():
        raise InvalidInputError("Total fuel must be finite")

    station_ids = [tank.station_id for tank in tanks]
    if len(station_ids) != len(set(station_ids)):
        raise InvalidInputError("Fuel system contains duplicate tank stations")

    for tank in tanks:
        if not tank.station_id.strip() or not tank.name.strip():
            raise InvalidInputError("Every fuel tank requires an id and name")
        for value, label in (
            (tank.usable_capacity_gal, "usable capacity"),
            (tank.arm_in, "ARM"),
            (tank.density_lb_per_gal, "fuel density"),
        ):
            if not value.is_finite():
                raise InvalidInputError(f"Fuel tank '{tank.name}' {label} must be finite")
        if tank.usable_capacity_gal <= 0:
            raise InvalidInputError(f"Fuel tank '{tank.name}' usable capacity must be positive")
        if tank.density_lb_per_gal <= 0:
            raise InvalidInputError(f"Fuel tank '{tank.name}' density must be positive")
        if tank.fixed_full_quantity_gal is not None:
            if not tank.fixed_full_quantity_gal.is_finite() or tank.fixed_full_quantity_gal <= 0:
                raise InvalidInputError(
                    f"Fuel tank '{tank.name}' fixed allocation quantity must be positive and finite"
                )
            if tank.fixed_full_quantity_gal > tank.usable_capacity_gal:
                raise InvalidInputError(
                    f"Fuel tank '{tank.name}' fixed allocation quantity exceeds usable capacity"
                )

    densities = {tank.density_lb_per_gal for tank in tanks}
    if len(densities) > 1:
        raise InvalidInputError("All tanks in one total-fuel group must share the same fuel density")
    if total_gal < 0:
        raise InvalidInputError("Total fuel cannot be negative")
    capacity = total_capacity_gal(tanks)
    if total_gal > capacity:
        raise InvalidInputError(
            f"Total fuel ({compact_decimal(total_gal)} gal) exceeds combined usable capacity "
            f"({compact_decimal(capacity)} gal)"
        )
    return next(iter(densities))


def _fill_in_order(tanks: list[FuelTankSpec], total_gal: Decimal, density: Decimal) -> FuelAllocation:
    remaining = total_gal
    gallons_by_station: dict[str, Decimal] = {
        tank.station_id: Decimal("0") for tank in tanks
    }
    moment = Decimal("0")
    for tank in tanks:
        take = min(tank.usable_capacity_gal, remaining)
        gallons_by_station[tank.station_id] = take
        moment += take * density * tank.arm_in
        remaining -= take
        if remaining <= 0:
            break
    return FuelAllocation(gallons_by_station=gallons_by_station, total_moment_lb_in=moment)


def compute_fuel_allocation(tanks: list[FuelTankSpec], total_gal: Decimal) -> FuelAllocationResult:
    """Return minimum- and maximum-moment allocations for one total fuel quantity."""
    density = _validate_group(tanks, total_gal)
    total_weight = total_gal * density
    mode = detect_mode(tanks)

    min_allocation = _fill_in_order(sorted(tanks, key=lambda tank: tank.arm_in), total_gal, density)
    max_allocation = _fill_in_order(
        sorted(tanks, key=lambda tank: tank.arm_in, reverse=True), total_gal, density
    )

    return FuelAllocationResult(
        mode=mode,
        total_gal=total_gal,
        total_weight_lb=total_weight,
        min_allocation=min_allocation,
        max_allocation=max_allocation,
    )


def compute_fixed_allocation(tanks: list[FuelTankSpec], total_gal: Decimal) -> FuelAllocation:
    """Apply only the profile's explicitly confirmed fixed allocation rule."""
    density = _validate_group(tanks, total_gal)
    orders = [tank.allocation_order for tank in tanks]
    if any(order is None for order in orders):
        raise InvalidInputError("Every tank in a fixed-allocation system requires an allocation order")
    if len(orders) != len(set(orders)):
        raise InvalidInputError("Fixed-allocation tank order values must be unique")

    ordered = sorted(tanks, key=lambda tank: tank.allocation_order)
    remaining = total_gal
    gallons_by_station: dict[str, Decimal] = {
        tank.station_id: Decimal("0") for tank in tanks
    }
    moment = Decimal("0")
    for tank in ordered:
        cap = (
            tank.fixed_full_quantity_gal
            if tank.fixed_full_quantity_gal is not None
            else tank.usable_capacity_gal
        )
        take = min(cap, remaining)
        gallons_by_station[tank.station_id] = take
        moment += take * density * tank.arm_in
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        raise InvalidInputError("Total fuel exceeds the confirmed fixed-allocation capacity")
    return FuelAllocation(gallons_by_station=gallons_by_station, total_moment_lb_in=moment)


def classify_cg_range(
    envelope: CGEnvelope | None, weight_lb: Decimal, cg_min: Decimal, cg_max: Decimal
) -> tuple[FuelRangeStatus | None, CGCheckResult | None, CGCheckResult | None]:
    """Classify every possible CG in a continuous range against the envelope.

    Endpoint checks alone are not enough: one endpoint can be forward of the envelope and the
    other aft of it, while the interval between them contains valid CG values. That case requires
    the actual tank split; it is not "out for all possible splits".
    """
    if envelope is None:
        return None, None, None
    if not all(value.is_finite() for value in (weight_lb, cg_min, cg_max)):
        raise InvalidInputError("Weight and CG range values must be finite")

    lower_cg, upper_cg = (cg_min, cg_max) if cg_min <= cg_max else (cg_max, cg_min)
    check_forward = envelope.check(weight_lb, lower_cg)
    check_aft = envelope.check(weight_lb, upper_cg)
    limits = envelope.limits_at(weight_lb)

    # Outside the published envelope weight range, no CG split can make the condition valid.
    if limits is None:
        return FuelRangeStatus.OUT_ALL, check_forward, check_aft

    forward_limit, aft_limit = limits
    if upper_cg < forward_limit - EPSILON:
        status = FuelRangeStatus.OUT_ALL
    elif lower_cg > aft_limit + EPSILON:
        status = FuelRangeStatus.OUT_ALL
    elif lower_cg >= forward_limit - EPSILON and upper_cg <= aft_limit + EPSILON:
        status = FuelRangeStatus.WITHIN_ALL
    else:
        status = FuelRangeStatus.EXACT_SPLIT_REQUIRED

    return status, check_forward, check_aft
