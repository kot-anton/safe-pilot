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

ENGINE_VERSION = "1.0.0"

_WORST_STATUS_ORDER = {
    LimitStatus.WITHIN: 0,
    LimitStatus.ON_LIMIT: 1,
    LimitStatus.OUT_OF_LIMITS: 2,
}


def _worse(a: LimitStatus, b: LimitStatus) -> LimitStatus:
    return a if _WORST_STATUS_ORDER[a] >= _WORST_STATUS_ORDER[b] else b


def _validate_inputs(profile: AircraftProfile, calc_input: CalculationInput) -> None:
    known_ids = {s.station_id for s in profile.stations}

    for load in calc_input.loads:
        if load.weight_lb < 0:
            raise InvalidInputError(f"Load weight at station '{load.station_id}' cannot be negative")
        if load.station_id not in known_ids:
            raise InvalidInputError(f"Unknown station id '{load.station_id}'")
        station = profile.station(load.station_id)
        if station.is_adjustable_arm:
            if load.arm_in is None:
                raise InvalidInputError(f"Station '{station.name}' requires an ARM to be specified")
            if not (station.minimum_arm_in <= load.arm_in <= station.maximum_arm_in):
                raise InvalidInputError(
                    f"ARM {load.arm_in} for station '{station.name}' is outside its adjustable "
                    f"range {station.minimum_arm_in}-{station.maximum_arm_in}"
                )

    for fuel in calc_input.fuel:
        if fuel.station_id not in known_ids:
            raise InvalidInputError(f"Unknown fuel station id '{fuel.station_id}'")
        station = profile.station(fuel.station_id)
        if station.station_type != StationType.FUEL:
            raise InvalidInputError(f"Station '{station.name}' is not a fuel station")
        if fuel.starting_gal < 0:
            raise InvalidInputError(f"Starting fuel at '{station.name}' cannot be negative")
        if fuel.starting_gal > station.maximum_volume_gal:
            raise InvalidInputError(
                f"Starting fuel at '{station.name}' ({fuel.starting_gal} gal) exceeds "
                f"tank capacity ({station.maximum_volume_gal} gal)"
            )
        if fuel.taxi_burn_gal > fuel.starting_gal:
            raise InvalidInputError(f"Taxi fuel burn at '{station.name}' exceeds starting fuel")
        if fuel.taxi_burn_gal + fuel.enroute_burn_gal > fuel.starting_gal:
            raise InvalidInputError(
                f"Total fuel burn at '{station.name}' exceeds starting fuel (landing fuel would be negative)"
            )


def _load_moment(profile: AircraftProfile, load: LoadItemInput) -> tuple[Decimal, Decimal]:
    station = profile.station(load.station_id)
    arm = load.arm_in if station.is_adjustable_arm else station.default_arm_in
    return load.weight_lb, load.weight_lb * arm


def _station_results_for_loads(
    profile: AircraftProfile, loads: list[LoadItemInput]
) -> list[StationLoadResult]:
    results = []
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

    for r in all_station_results:
        total_weight += r.weight_lb
        total_moment += r.moment_lb_in

    cg = total_moment / total_weight if total_weight != 0 else Decimal("0")
    cg_check = profile.envelope.check(total_weight, cg)

    weight_status = LimitStatus.WITHIN
    if weight_limit is not None:
        if total_weight > weight_limit:
            weight_status = LimitStatus.OUT_OF_LIMITS
        elif total_weight == weight_limit:
            weight_status = LimitStatus.ON_LIMIT

    station_status = LimitStatus.WITHIN
    for r in all_station_results:
        if r.over_station_limit or r.over_capacity:
            station_status = LimitStatus.OUT_OF_LIMITS

    overall = _worse(_worse(weight_status, cg_check.status), station_status)

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
    """Runs the full ramp / takeoff / landing calculation. Raises InvalidInputError on bad input."""
    _validate_inputs(profile, calc_input)

    load_station_results = _station_results_for_loads(profile, calc_input.loads)

    ramp_fuel_results = [_fuel_station_result(profile, f, f.starting_gal) for f in calc_input.fuel]
    ramp = _build_phase(
        "RAMP", profile, load_station_results, ramp_fuel_results, profile.max_ramp_weight_lb
    )

    takeoff_fuel_results = [
        _fuel_station_result(profile, f, f.starting_gal - f.taxi_burn_gal) for f in calc_input.fuel
    ]
    takeoff = _build_phase(
        "TAKEOFF", profile, load_station_results, takeoff_fuel_results, profile.max_takeoff_weight_lb
    )

    if profile.max_zero_fuel_weight_lb is not None:
        zero_fuel_weight = profile.basic_empty_weight_lb + sum(
            (r.weight_lb for r in load_station_results), Decimal("0")
        )
        if zero_fuel_weight > profile.max_zero_fuel_weight_lb:
            takeoff = dataclasses.replace(
                takeoff, overall_status=_worse(takeoff.overall_status, LimitStatus.OUT_OF_LIMITS)
            )

    landing_evaluated = calc_input.landing_evaluated
    landing = None
    if landing_evaluated:
        landing_fuel_results = [
            _fuel_station_result(
                profile, f, f.starting_gal - f.taxi_burn_gal - f.enroute_burn_gal
            )
            for f in calc_input.fuel
        ]
        landing = _build_phase(
            "LANDING",
            profile,
            load_station_results,
            landing_fuel_results,
            profile.max_landing_weight_lb,
        )

    overall = _worse(ramp.overall_status, takeoff.overall_status)
    if landing is not None:
        overall = _worse(overall, landing.overall_status)

    return CalculationResult(
        ramp=ramp,
        takeoff=takeoff,
        landing=landing,
        landing_evaluated=landing_evaluated,
        overall_status=overall,
    )
