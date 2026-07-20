from decimal import Decimal as D

import pytest

from app.domain.calculator import calculate
from app.domain.envelope import LimitStatus
from app.domain.exceptions import InvalidInputError
from app.domain.models import CalculationInput, FuelStationInput, LoadItemInput
from tests.conftest import make_test_profile


def basic_input(**overrides):
    loads = overrides.pop(
        "loads",
        [
            LoadItemInput(station_id="front_seats", weight_lb=D("340")),
            LoadItemInput(station_id="rear_seats", weight_lb=D("0")),
            LoadItemInput(station_id="baggage_1", weight_lb=D("20")),
        ],
    )
    fuel = overrides.pop(
        "fuel",
        [
            FuelStationInput(station_id="main_fuel", starting_gal=D("30")),
            FuelStationInput(station_id="aux_fuel", starting_gal=D("0")),
        ],
    )
    return CalculationInput(loads=loads, fuel=fuel)


def test_moment_and_cg_calculation():
    profile = make_test_profile()
    calc_input = basic_input()
    result = calculate(profile, calc_input)

    # empty: 1500 lb @ moment 58500
    # front seats: 340 * 37.0 = 12580
    # baggage: 20 * 95.0 = 1900
    # main fuel: 30 gal * 6.0 lb/gal = 180 lb * 48.0 = 8640
    expected_weight = D("1500") + D("340") + D("20") + D("180")
    expected_moment = D("58500") + D("12580") + D("1900") + D("8640")
    expected_cg = expected_moment / expected_weight

    assert result.ramp.total_weight_lb == expected_weight
    assert result.ramp.cg_in == expected_cg


def test_overweight_condition():
    profile = make_test_profile()
    calc_input = basic_input(
        loads=[
            LoadItemInput(station_id="front_seats", weight_lb=D("340")),
            LoadItemInput(station_id="rear_seats", weight_lb=D("340")),
            LoadItemInput(station_id="baggage_1", weight_lb=D("100")),
        ],
        fuel=[
            FuelStationInput(station_id="main_fuel", starting_gal=D("40")),
            FuelStationInput(station_id="aux_fuel", starting_gal=D("20")),
        ],
    )
    result = calculate(profile, calc_input)
    assert result.ramp.total_weight_lb > profile.max_ramp_weight_lb
    assert result.overall_status == LimitStatus.OUT_OF_LIMITS


def test_station_maximum_weight_violation():
    profile = make_test_profile()
    calc_input = basic_input(
        loads=[
            LoadItemInput(station_id="front_seats", weight_lb=D("340")),
            LoadItemInput(station_id="rear_seats", weight_lb=D("0")),
            LoadItemInput(station_id="baggage_1", weight_lb=D("150")),  # max is 120
        ]
    )
    result = calculate(profile, calc_input)
    assert result.overall_status == LimitStatus.OUT_OF_LIMITS
    baggage_result = next(s for s in result.ramp.station_results if s.station_id == "baggage_1")
    assert baggage_result.over_station_limit


def test_fuel_tank_capacity_violation_rejected():
    profile = make_test_profile()
    calc_input = basic_input(
        fuel=[
            FuelStationInput(station_id="main_fuel", starting_gal=D("50")),  # max 40
            FuelStationInput(station_id="aux_fuel", starting_gal=D("0")),
        ]
    )
    with pytest.raises(InvalidInputError):
        calculate(profile, calc_input)


def test_ramp_takeoff_landing_fuel_subtraction():
    profile = make_test_profile()
    calc_input = basic_input(
        fuel=[
            FuelStationInput(
                station_id="main_fuel",
                starting_gal=D("30"),
                taxi_burn_gal=D("1"),
                enroute_burn_gal=D("10"),
            ),
            FuelStationInput(station_id="aux_fuel", starting_gal=D("0")),
        ]
    )
    result = calculate(profile, calc_input)

    assert result.landing_evaluated is True
    assert result.landing is not None

    density = D("6.0")
    assert result.ramp.total_weight_lb - result.takeoff.total_weight_lb == D("1") * density
    assert result.takeoff.total_weight_lb - result.landing.total_weight_lb == D("10") * density


def test_landing_not_evaluated_when_no_burn_provided():
    profile = make_test_profile()
    calc_input = basic_input()  # no taxi/enroute burn at all
    result = calculate(profile, calc_input)
    assert result.landing_evaluated is False
    assert result.landing is None


def test_multiple_fuel_tanks_with_different_arms():
    profile = make_test_profile()
    calc_input = basic_input(
        fuel=[
            FuelStationInput(station_id="main_fuel", starting_gal=D("10")),
            FuelStationInput(station_id="aux_fuel", starting_gal=D("10")),
        ]
    )
    result = calculate(profile, calc_input)

    main_result = next(s for s in result.ramp.station_results if s.station_id == "main_fuel")
    aux_result = next(s for s in result.ramp.station_results if s.station_id == "aux_fuel")

    assert main_result.arm_in == D("48.0")
    assert aux_result.arm_in == D("20.0")
    assert main_result.weight_lb == aux_result.weight_lb == D("60")  # 10 gal * 6.0 lb/gal
    assert main_result.moment_lb_in != aux_result.moment_lb_in


def test_taxi_burn_greater_than_starting_fuel_rejected():
    profile = make_test_profile()
    calc_input = basic_input(
        fuel=[
            FuelStationInput(station_id="main_fuel", starting_gal=D("5"), taxi_burn_gal=D("6")),
            FuelStationInput(station_id="aux_fuel", starting_gal=D("0")),
        ]
    )
    with pytest.raises(InvalidInputError):
        calculate(profile, calc_input)


def test_no_envelope_reports_cg_not_evaluated_but_still_checks_weight():
    """An aircraft with no CG envelope on file (explicitly skipped during setup) must still
    catch weight violations -- it just can't say anything about CG."""
    profile = make_test_profile(envelope=None)
    calc_input = basic_input(
        loads=[
            LoadItemInput(station_id="front_seats", weight_lb=D("500")),
            LoadItemInput(station_id="rear_seats", weight_lb=D("500")),
            LoadItemInput(station_id="baggage_1", weight_lb=D("120")),
        ],
        fuel=[
            FuelStationInput(station_id="main_fuel", starting_gal=D("40")),
            FuelStationInput(station_id="aux_fuel", starting_gal=D("20")),
        ],
    )
    result = calculate(profile, calc_input)

    assert result.ramp.cg_check is None
    assert result.takeoff.cg_check is None
    assert result.ramp.total_weight_lb > profile.max_ramp_weight_lb
    assert result.overall_status == LimitStatus.OUT_OF_LIMITS


def test_no_envelope_within_weight_limits_reports_within():
    profile = make_test_profile(envelope=None)
    calc_input = basic_input()
    result = calculate(profile, calc_input)

    assert result.ramp.cg_check is None
    assert result.overall_status == LimitStatus.WITHIN


def test_adjustable_arm_out_of_range_rejected():
    from app.domain.models import StationProfile, StationType

    profile = make_test_profile(
        stations=[
            StationProfile(
                station_id="custom1",
                name="Custom Station",
                station_type=StationType.CUSTOM,
                default_arm_in=D("100"),
                is_adjustable_arm=True,
                minimum_arm_in=D("90"),
                maximum_arm_in=D("110"),
            )
        ]
    )
    calc_input = CalculationInput(
        loads=[LoadItemInput(station_id="custom1", weight_lb=D("10"), arm_in=D("200"))],
        fuel=[],
    )
    with pytest.raises(InvalidInputError):
        calculate(profile, calc_input)
