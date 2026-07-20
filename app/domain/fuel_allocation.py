"""Total-fuel allocation math for the "one total gallons number" calculation flow.

A pilot filling in the standard 4-question flow usually knows total usable fuel on board,
not the exact gallons in each physical tank. When every fuel tank in the group shares the
same ARM, the split doesn't matter -- the resulting moment is exact regardless. When tanks
have different ARMs and the split is unknown, the actual CG could be anywhere within the
mathematically possible range, so this module computes that range instead of inventing one
number. Never assumes a "main tanks first" or "aux tanks first" rule -- that requires an
explicit, confirmed FIXED_ALLOCATION rule on the aircraft profile (see FuelSystem in
app.database.models), which this module also supports when given one.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.domain.envelope import CGCheckResult, CGEnvelope, LimitStatus
from app.domain.exceptions import InvalidInputError


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
    # Only meaningful for FIXED_ALLOCATION -- the confirmed, deterministic fill order/quantity.
    allocation_order: int | None = None
    fixed_full_quantity_gal: Decimal | None = None


@dataclass(frozen=True)
class FuelAllocation:
    """One concrete, capacity-respecting split of `total_gal` across tanks."""

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
    return sum((t.usable_capacity_gal for t in tanks), Decimal("0"))


def detect_mode(tanks: list[FuelTankSpec]) -> FuelInputMode:
    """Auto-detects the safest mode from tank ARMs alone. Never guesses an allocation rule --
    FIXED_ALLOCATION is only ever used when explicitly requested via `compute_fixed_allocation`
    for a profile that has confirmed one."""
    if len(tanks) <= 1:
        return FuelInputMode.SINGLE_ARM
    arms = {t.arm_in for t in tanks}
    return FuelInputMode.SINGLE_ARM if len(arms) == 1 else FuelInputMode.UNKNOWN_SPLIT_RANGE


def _validate_group(tanks: list[FuelTankSpec], total_gal: Decimal) -> Decimal:
    if not tanks:
        raise InvalidInputError("Fuel group has no tanks")
    densities = {t.density_lb_per_gal for t in tanks}
    if len(densities) > 1:
        raise InvalidInputError("All tanks in one total-fuel group must share the same fuel density")
    if total_gal < 0:
        raise InvalidInputError("Total fuel cannot be negative")
    capacity = total_capacity_gal(tanks)
    if total_gal > capacity:
        raise InvalidInputError(
            f"Total fuel ({total_gal} gal) exceeds combined usable capacity ({capacity} gal)"
        )
    return densities.pop()


def _fill_in_order(tanks: list[FuelTankSpec], total_gal: Decimal, density: Decimal) -> FuelAllocation:
    remaining = total_gal
    gallons_by_station: dict[str, Decimal] = {t.station_id: Decimal("0") for t in tanks}
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
    """Returns the mathematically possible minimum- and maximum-moment allocations of
    `total_gal` across `tanks`. For SINGLE_ARM (all tanks share one ARM), both allocations
    have the same moment -- the result is exact regardless of the actual physical split."""
    density = _validate_group(tanks, total_gal)
    total_weight = total_gal * density
    mode = detect_mode(tanks)

    ascending = sorted(tanks, key=lambda t: t.arm_in)
    descending = sorted(tanks, key=lambda t: t.arm_in, reverse=True)
    min_allocation = _fill_in_order(ascending, total_gal, density)
    max_allocation = _fill_in_order(descending, total_gal, density)

    return FuelAllocationResult(
        mode=mode,
        total_gal=total_gal,
        total_weight_lb=total_weight,
        min_allocation=min_allocation,
        max_allocation=max_allocation,
    )


def compute_fixed_allocation(tanks: list[FuelTankSpec], total_gal: Decimal) -> FuelAllocation:
    """FIXED_ALLOCATION: fills tanks in the profile's confirmed `allocation_order`, each up to
    its `fixed_full_quantity_gal` (or full usable capacity if not set), never a guessed rule."""
    density = _validate_group(tanks, total_gal)
    ordered = sorted(
        tanks, key=lambda t: t.allocation_order if t.allocation_order is not None else 0
    )
    remaining = total_gal
    gallons_by_station: dict[str, Decimal] = {t.station_id: Decimal("0") for t in tanks}
    moment = Decimal("0")
    for tank in ordered:
        cap = tank.fixed_full_quantity_gal if tank.fixed_full_quantity_gal is not None else tank.usable_capacity_gal
        take = min(cap, remaining)
        gallons_by_station[tank.station_id] = take
        moment += take * density * tank.arm_in
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        raise InvalidInputError(
            "Total fuel exceeds the aircraft's confirmed fixed-allocation capacity"
        )
    return FuelAllocation(gallons_by_station=gallons_by_station, total_moment_lb_in=moment)


def classify_cg_range(
    envelope: CGEnvelope | None, weight_lb: Decimal, cg_min: Decimal, cg_max: Decimal
) -> tuple[FuelRangeStatus | None, CGCheckResult | None, CGCheckResult | None]:
    """Classifies a possible-CG range (from an unknown fuel split) against the envelope.

    Returns (None, None, None) when there is no envelope to check against -- CG is simply
    not evaluated, same convention as the rest of the domain layer.
    """
    if envelope is None:
        return None, None, None

    lower_cg, upper_cg = (cg_min, cg_max) if cg_min <= cg_max else (cg_max, cg_min)
    check_forward = envelope.check(weight_lb, lower_cg)
    check_aft = envelope.check(weight_lb, upper_cg)

    forward_ok = check_forward.status != LimitStatus.OUT_OF_LIMITS
    aft_ok = check_aft.status != LimitStatus.OUT_OF_LIMITS

    if forward_ok and aft_ok:
        status = FuelRangeStatus.WITHIN_ALL
    elif not forward_ok and not aft_ok:
        status = FuelRangeStatus.OUT_ALL
    else:
        status = FuelRangeStatus.EXACT_SPLIT_REQUIRED

    return status, check_forward, check_aft
