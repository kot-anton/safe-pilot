"""Deterministic Weight & Balance calculation engine. Pure Python / Decimal, no I/O."""
from __future__ import annotations

import dataclasses
from decimal import Decimal

from app.domain.envelope import LimitStatus
from app.domain.exceptions import InvalidInputError
from app.domain.models import (
    AircraftProfile,
    CalculationInput,
    CalculationResult,
    FuelStationInput,
    LoadItemInput,
    PhaseResult,
    StationLoadResult,
    StationType,
)

ENGINE_VERSION = "1.2.0"

_WORST_STATUS_ORDER = {
    LimitStatus.WITHIN: 0,
    LimitStatus.ON_LIMIT: 1,
    LimitStatus.OUT_OF_LIMITS: 2,
}


def _worse(a: LimitStatus, b: LimitStatus) -> LimitStatus:
    return a if _WORST_STATUS_ORDER[a] >= _WORST_STATUS_ORDER[b] else b


def _require_finite(value: Decimal, label: str) -> None:
    if not value.is_finite():
        raise InvalidInputError(f"{label} must be finite")


def _validate_inputs(profile: AircraftProfile, calc_input: CalculationInput) -> None:
    known_ids = {station.station_id for station in profile.stations}
    load_ids = [load.station_id for load in calc_input.loads]
    fuel_ids = [fuel.station_id for fuel in calc_input.fuel]

    if len(load_ids) != len(set(load_ids)):
        raise InvalidInputError("The same load station was entered more than once")
    if len(fuel_ids) != len(set(fuel_ids)):
        raise InvalidInputError("The same fuel station was entered more than once")
    overlap = set(load_ids) & set(fuel_ids)
    if overlap:
        raise InvalidInputError(
            f"A station cannot be entered as both load and fuel: {', '.join(sorted(overlap))}"
        )

    for load in calc_input.loads:
        _require_finite(load.weight_lb, f"Load weight at station '{load.station_id}'")
        if load.arm_in is not None:
            _require_finite(load.arm_in, f"ARM at station '{load.station_id}'")
        if load.weight_lb < 0:
            raise InvalidInputError(f"Load weight at station '{load.station_id}' cannot be negative")
        if load.station_id not in known_ids:
            raise InvalidInputError(f"Unknown station id '{load.station_id}'")
        station = profile.station(load.station_id)
        if station.station_type == StationType.FUEL:
            raise InvalidInputError(
                f"Fuel station '{station.name}' must be entered in gallons, not as a generic load"
            )
        if station.is_adjustable_arm:
            if load.arm_in is None:
                raise InvalidInputError(f"Station '{station.name}' requires an ARM to be specified")
            if not (station.minimum_arm_in <= load.arm_in <= station.maximum_arm_in):
                raise InvalidInputError(
                    f"ARM {load.arm_in} for station '{station.name}' is outside its adjustable "
                    f"range {station.minimum_arm_in}-{station.maximum_arm_in}"
                )

    for fuel in calc_input.fuel:
        for value, label in (
            (fuel.starting_gal, "Starting fuel"),
            (fuel.taxi_burn_gal, "Taxi fuel burn"),
            (fuel.enroute_burn_gal, "Enroute fuel burn"),
        ):
            _require_finite(value, f"{label} at station '{fuel.station_id}'")
        if fuel.station_id not in known_ids:
            raise InvalidInputError(f"Unknown fuel station id '{fuel.station_id}'")
        station = profile.station(fuel.station_id)
        if station.station_type != StationType.FUEL:
            raise InvalidInputError(f"Station '{station.name}' is not a fuel station")
        if fuel.starting_gal < 0:
            raise InvalidInputError(f"Starting fuel at '{station.name}' cannot be negative")
        if fuel.taxi_burn_gal < 0:
            raise InvalidInputError(f"Taxi fuel burn at '{station.name}' cannot be negative")
        if fuel.enroute_burn_gal < 0:
            raise InvalidInputError(f"Enroute fuel burn at '{station.name}' cannot be negative")
        if fuel.starting_gal > station.maximum_volume_gal:
            raise InvalidInputError(
                f"Starting fuel at '{station.name}' ({fuel.starting_gal} gal) exceeds "
                f"tank capacity ({station.maximum_volume_gal} gal)"
            )
        if fuel.taxi_burn_gal > fuel.starting_gal:
            raise InvalidInputError(f"Taxi fuel burn at '{station.name}' exceeds starting fuel")
        if fuel.taxi_burn_gal + fuel.enroute_burn_gal > fuel.starting_gal:
            raise InvalidInputError(
                f"Total fuel burn at '{station.name}' exceeds starting fuel "
                "(landing fuel would be negative)"
            )


def _station_results_for_loads(
    profile: AircraftProfile, loads: list[LoadItemInput]
) -> list[StationLoadResult]:
    results: list[StationLoadResult] = []
    for load in loads:
        station = profile.station(load.station_id)
        arm = load.arm_in if station.is_adjustable_arm else station.default_arm_in
        moment = load.weight_lb * arm
        over_limit = station.maximum_weight_lb is not None and load.weight_lb > station.maximum_weight_lb
        results.append(
            StationLoadResult(
                station_id=station.station_id,
                name=station.name,
                weight_lb=load.weight_lb,
                arm_in=arm,
                moment_lb_in=moment,
                over_station_limit=over_limit,
            )
        )
    return results


def _fuel_station_result(
    profile: AircraftProfile, fuel: FuelStationInput, gallons: Decimal
) -> StationLoadResult:
    station = profile.station(fuel.station_id)
    weight = gallons * station.fuel_density_lb_per_gal
    moment = weight * station.default_arm_in
    over_capacity = gallons > station.maximum_volume_gal
    return StationLoadResult(
        station_id=station.station_id,
        name=station.name,
        weight_lb=weight,
        arm_in=station.default_arm_in,
        moment_lb_in=moment,
        over_station_limit=False,
        over_capacity=over_capacity,
    )


def _build_phase(
    phase_name: str,
    profile: AircraftProfile,
    load_results: list[StationLoadResult],
    fuel_results: list[StationLoadResult],
    weight_limit: Decimal | None,
) -> PhaseResult:
    total_weight = profile.basic_empty_weight_lb
    total_moment = profile.basic_empty_moment_lb_in
    all_station_results = load_results + fuel_results

    for result in all_station_results:
        total_weight += result.weight_lb
        total_moment += result.moment_lb_in

    if total_weight <= 0:
        raise InvalidInputError("Calculated aircraft weight must be greater than zero")
    cg = total_moment / total_weight
    cg_check = profile.envelope.check(total_weight, cg) if profile.envelope is not None else None

    weight_status = LimitStatus.WITHIN
    if weight_limit is not None:
        if total_weight > weight_limit:
            weight_status = LimitStatus.OUT_OF_LIMITS
        elif total_weight == weight_limit:
            weight_status = LimitStatus.ON_LIMIT

    station_status = LimitStatus.WITHIN
    for result in all_station_results:
        if result.over_station_limit or result.over_capacity:
            station_status = LimitStatus.OUT_OF_LIMITS

    overall = _worse(weight_status, station_status)
    if cg_check is not None:
        overall = _worse(overall, cg_check.status)

    return PhaseResult(
        phase=phase_name,
        total_weight_lb=total_weight,
        weight_limit_lb=weight_limit,
        cg_in=cg,
        cg_check=cg_check,
        station_results=all_station_results,
        weight_status=weight_status,
        overall_status=overall,
    )


def calculate(profile: AircraftProfile, calc_input: CalculationInput) -> CalculationResult:
    """Run the full ramp / takeoff / landing calculation.

    ``InvalidInputError`` is raised for malformed or physically impossible input. Published
    limit exceedances are returned as deterministic statuses rather than exceptions.
    """
    _validate_inputs(profile, calc_input)

    load_station_results = _station_results_for_loads(profile, calc_input.loads)
    zero_fuel_weight = profile.basic_empty_weight_lb + sum(
        (result.weight_lb for result in load_station_results), Decimal("0")
    )
    zero_fuel_status = LimitStatus.WITHIN
    if profile.max_zero_fuel_weight_lb is not None:
        if zero_fuel_weight > profile.max_zero_fuel_weight_lb:
            zero_fuel_status = LimitStatus.OUT_OF_LIMITS
        elif zero_fuel_weight == profile.max_zero_fuel_weight_lb:
            zero_fuel_status = LimitStatus.ON_LIMIT

    ramp_fuel_results = [_fuel_station_result(profile, fuel, fuel.starting_gal) for fuel in calc_input.fuel]
    ramp = _build_phase(
        "RAMP", profile, load_station_results, ramp_fuel_results, profile.max_ramp_weight_lb
    )

    takeoff_fuel_results = [
        _fuel_station_result(profile, fuel, fuel.starting_gal - fuel.taxi_burn_gal)
        for fuel in calc_input.fuel
    ]
    takeoff = _build_phase(
        "TAKEOFF", profile, load_station_results, takeoff_fuel_results, profile.max_takeoff_weight_lb
    )

    if zero_fuel_status != LimitStatus.WITHIN:
        ramp = dataclasses.replace(
            ramp, overall_status=_worse(ramp.overall_status, zero_fuel_status)
        )
        takeoff = dataclasses.replace(
            takeoff, overall_status=_worse(takeoff.overall_status, zero_fuel_status)
        )

    landing_evaluated = calc_input.landing_evaluated
    landing = None
    if landing_evaluated:
        landing_fuel_results = [
            _fuel_station_result(
                profile,
                fuel,
                fuel.starting_gal - fuel.taxi_burn_gal - fuel.enroute_burn_gal,
            )
            for fuel in calc_input.fuel
        ]
        landing = _build_phase(
            "LANDING",
            profile,
            load_station_results,
            landing_fuel_results,
            profile.max_landing_weight_lb,
        )
        if zero_fuel_status != LimitStatus.WITHIN:
            landing = dataclasses.replace(
                landing, overall_status=_worse(landing.overall_status, zero_fuel_status)
            )

    overall = _worse(ramp.overall_status, takeoff.overall_status)
    if landing is not None:
        overall = _worse(overall, landing.overall_status)

    return CalculationResult(
        ramp=ramp,
        takeoff=takeoff,
        landing=landing,
        landing_evaluated=landing_evaluated,
        zero_fuel_weight_lb=zero_fuel_weight,
        zero_fuel_limit_lb=profile.max_zero_fuel_weight_lb,
        zero_fuel_status=zero_fuel_status,
        overall_status=overall,
    )
