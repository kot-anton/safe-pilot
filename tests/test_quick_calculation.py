from decimal import Decimal as D

import pytest

from app.domain.envelope import LimitStatus
from app.domain.exceptions import InvalidInputError
from app.domain.fuel_allocation import FuelRangeStatus
from app.domain.quick_calculation import run_quick_calculation
from tests.conftest import make_test_profile


def test_quick_calculation_within_limits():
    profile = make_test_profile()  # front/rear/baggage/main_fuel/aux_fuel, envelope 2200-2550
    # Weight must land inside the envelope's published range (2200-2550) to be meaningfully checked.
    result = run_quick_calculation(profile, front_lb=D("340"), rear_lb=D("300"), baggage_lb=D("20"), total_fuel_gal=D("30"))
    assert result.overall_status in (LimitStatus.WITHIN, LimitStatus.ON_LIMIT)
    assert result.weight_status == LimitStatus.WITHIN


def test_quick_calculation_overweight():
    profile = make_test_profile()
    result = run_quick_calculation(profile, front_lb=D("400"), rear_lb=D("400"), baggage_lb=D("120"), total_fuel_gal=D("60"))
    assert result.weight_status == LimitStatus.OUT_OF_LIMITS
    assert result.overall_status == LimitStatus.OUT_OF_LIMITS


def test_quick_calculation_full_fuel_is_exact():
    """main_fuel and aux_fuel have different ARMs, but at full capacity the split is forced."""
    profile = make_test_profile()
    result = run_quick_calculation(profile, front_lb=D("340"), rear_lb=D("0"), baggage_lb=D("0"), total_fuel_gal=D("60"))
    assert result.is_exact
    assert result.cg_forward == result.cg_aft


def test_quick_calculation_partial_fuel_unknown_split_gives_range():
    profile = make_test_profile()
    result = run_quick_calculation(profile, front_lb=D("340"), rear_lb=D("0"), baggage_lb=D("0"), total_fuel_gal=D("20"))
    assert not result.is_exact
    assert result.cg_forward < result.cg_aft


def test_quick_calculation_rejects_load_at_missing_station():
    from app.domain.models import AircraftProfile, StationProfile, StationType
    from app.domain.envelope import CGEnvelope, EnvelopeRow

    profile = AircraftProfile(
        tail_number="N1", revision_number=1,
        basic_empty_weight_lb=D("1000"), basic_empty_moment_lb_in=D("30000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(station_id="front", name="Front", station_type=StationType.FRONT_SEATS, default_arm_in=D("30")),
            StationProfile(station_id="fuel", name="Fuel", station_type=StationType.FUEL, default_arm_in=D("40"), maximum_volume_gal=D("30"), fuel_density_lb_per_gal=D("6")),
        ],
        envelope=CGEnvelope([EnvelopeRow(D("1200"), D("28"), D("55")), EnvelopeRow(D("1600"), D("28"), D("55"))]),
    )
    # no rear-seat station configured on this aircraft
    with pytest.raises(InvalidInputError):
        run_quick_calculation(profile, front_lb=D("100"), rear_lb=D("50"), baggage_lb=D("0"), total_fuel_gal=D("10"))


def test_quick_calculation_fuel_above_capacity_rejected():
    profile = make_test_profile()
    with pytest.raises(InvalidInputError):
        run_quick_calculation(profile, front_lb=D("0"), rear_lb=D("0"), baggage_lb=D("0"), total_fuel_gal=D("100"))


def test_quick_calculation_exact_split_required_status():
    """Constructed so the possible-CG range straddles the envelope boundary."""
    from app.domain.models import AircraftProfile, StationProfile, StationType
    from app.domain.envelope import CGEnvelope, EnvelopeRow

    profile = AircraftProfile(
        tail_number="N2", revision_number=1,
        basic_empty_weight_lb=D("1000"), basic_empty_moment_lb_in=D("40000"),  # cg 40
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(station_id="main", name="Main Fuel", station_type=StationType.FUEL, default_arm_in=D("60"), maximum_volume_gal=D("30"), fuel_density_lb_per_gal=D("6")),
            StationProfile(station_id="aux", name="Aux Fuel", station_type=StationType.FUEL, default_arm_in=D("20"), maximum_volume_gal=D("30"), fuel_density_lb_per_gal=D("6")),
        ],
        envelope=CGEnvelope([EnvelopeRow(D("1100"), D("38"), D("45")), EnvelopeRow(D("1300"), D("38"), D("45"))]),
    )
    result = run_quick_calculation(profile, front_lb=D("0"), rear_lb=D("0"), baggage_lb=D("0"), total_fuel_gal=D("20"))
    assert result.fuel_range_status == FuelRangeStatus.EXACT_SPLIT_REQUIRED
    assert result.overall_status == LimitStatus.OUT_OF_LIMITS
